"""Tests for polling windows, statistics import and scheduling."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.sew_water.const import (
    CONF_SCAN_INTERVAL,
    POLL_HOUR,
    POLL_JITTER_MINUTES,
    STATISTIC_ID_MAINS,
)
from custom_components.sew_water.coordinator import BUSY_RETRY_SECONDS, SewCoordinator
from custom_components.sew_water.sew_client import DailyUsage, SewBusyError, SewProtocolError

from .conftest import BACKFILL_DAYS, TRAILING_WINDOW_DAYS, FakeClient, usage_for


async def read_rows(hass: HomeAssistant) -> list[tuple[datetime, float, float]]:
    """Return (start, state, sum) for every stored mains row, oldest first."""
    await async_wait_recording_done(hass)
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utcnow() - timedelta(days=4000),
        None,
        {STATISTIC_ID_MAINS},
        "hour",
        None,
        {"state", "sum"},
    )
    return [
        (dt_util.utc_from_timestamp(r["start"]), float(r["state"] or 0), float(r["sum"] or 0))
        for r in rows.get(STATISTIC_ID_MAINS, [])
    ]


def yesterday() -> date:
    """Local calendar day before today."""
    return dt_util.now().date() - timedelta(days=1)


async def test_first_run_backfills_90_days_into_statistics(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    start, end = fake_client.fetch_ranges[0]
    assert end == yesterday()
    assert (end - start).days + 1 == BACKFILL_DAYS

    rows = await read_rows(hass)
    assert len(rows) == BACKFILL_DAYS * 24
    first_start, first_state, first_sum = rows[0]
    assert dt_util.as_local(first_start).hour == 0
    assert dt_util.as_local(first_start).date() == start
    assert first_state == 10 and first_sum == 10
    # Hour 23 of the first day closes at the day's total.
    assert rows[23][2] == 240
    assert dt_util.as_local(rows[23][0]).hour == 23
    assert rows[-1][2] == 240 * BACKFILL_DAYS

    data = setup_integration.runtime_data.data
    assert data.total_litres == 240 * BACKFILL_DAYS
    assert data.latest is not None and data.latest.day == yesterday()
    assert len(data.window) == BACKFILL_DAYS


async def test_second_poll_uses_trailing_window_and_keeps_sum_consistent(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    coordinator: SewCoordinator = setup_integration.runtime_data
    await async_wait_recording_done(hass)
    # The portal corrects one day inside the window; everything else unchanged.
    corrected = yesterday() - timedelta(days=1)
    fake_client.litres_per_hour = lambda day: 20 if day == corrected else 10
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    start, end = fake_client.fetch_ranges[-1]
    assert end == yesterday()
    assert (end - start).days + 1 == TRAILING_WINDOW_DAYS

    rows = await read_rows(hass)
    assert len(rows) == BACKFILL_DAYS * 24  # rewritten in place, no duplicates
    by_day: dict[date, float] = {}
    for s, state, _total in rows:
        by_day[dt_util.as_local(s).date()] = by_day.get(dt_util.as_local(s).date(), 0.0) + state
    assert by_day[corrected] == 480
    # Running sum picks up from the day before the window and includes the correction.
    expected_total = 240 * BACKFILL_DAYS + 240
    assert rows[-1][2] == expected_total
    assert coordinator.data.total_litres == expected_total


async def test_zero_days_are_imported_but_not_latest(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    unpublished = yesterday()
    fake_client.litres_per_hour = lambda day: 0 if day == unpublished else 10
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    data = mock_config_entry.runtime_data.data
    assert data.latest is not None and data.latest.day == unpublished - timedelta(days=1)
    rows = await read_rows(hass)
    assert rows[-1][1] == 0


async def test_busy_portal_schedules_short_retry(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    coordinator: SewCoordinator = setup_integration.runtime_data
    fake_client.fetch_error = SewBusyError("Concurrent requests limit exceeded")
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.retry_after == BUSY_RETRY_SECONDS

    fake_client.fetch_error = SewBusyError("slow down", retry_after=42)
    await coordinator.async_refresh()
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.retry_after == 42


async def test_protocol_error_is_update_failed(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    coordinator: SewCoordinator = setup_integration.runtime_data
    fake_client.fetch_error = SewProtocolError("weird")
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.translation_key == "unexpected_response"
    assert "weird" in str(coordinator.last_exception)


async def test_default_interval_targets_poll_hour_with_jitter(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    coordinator: SewCoordinator = setup_integration.runtime_data
    now = dt_util.now()
    assert coordinator.update_interval is not None
    target = now + coordinator.update_interval
    expected = now.replace(hour=POLL_HOUR, minute=0, second=0, microsecond=0)
    if expected <= now:
        expected += timedelta(days=1)
    assert timedelta(0) <= target - expected <= timedelta(minutes=POLL_JITTER_MINUTES)


async def test_custom_interval_is_used_verbatim(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_SCAN_INTERVAL: 180})
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.runtime_data.update_interval == timedelta(minutes=180)


async def test_scheduled_poll_fires(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    coordinator: SewCoordinator = setup_integration.runtime_data
    fetches = len(fake_client.fetch_ranges)
    assert coordinator.update_interval is not None
    async_fire_time_changed(hass, dt_util.utcnow() + coordinator.update_interval + timedelta(seconds=5))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(fake_client.fetch_ranges) == fetches + 1


async def test_dst_start_day_folds_spilled_hour_into_last_row(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Melbourne's 23-hour day: 24 readings must not produce a row at the next day's midnight."""
    await hass.config.async_set_time_zone("Australia/Melbourne")
    coordinator: SewCoordinator = setup_integration.runtime_data
    dst_start = date(2026, 10, 4)
    rows = coordinator._hourly_rows(usage_for(dst_start, 10))
    assert len(rows) == 23
    assert all(dt_util.as_local(start).date() == dst_start for start, _ in rows)
    assert rows[-1][1] == 20  # hour 23's reading folded into hour 22's row
    assert sum(litres for _, litres in rows) == 240


async def test_day_without_hourly_readings_is_one_midnight_row(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    coordinator: SewCoordinator = setup_integration.runtime_data
    day = usage_for(yesterday(), 0)
    day = DailyUsage(day=day.day, litres=0, readings=(), serial=None, message=None, available=False)
    rows = coordinator._hourly_rows(day)
    assert rows == [(dt_util.start_of_local_day(yesterday()), 0.0)]


async def test_import_with_no_days_keeps_existing_total(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    coordinator: SewCoordinator = setup_integration.runtime_data
    await async_wait_recording_done(hass)
    total = await coordinator._async_import_statistics([])
    assert total == 240 * BACKFILL_DAYS
