"""Data coordinator for the South East Water integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
import random

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

from .const import (
    BACKFILL_DAYS,
    CONF_BILLING_ACCOUNT_ID,
    CONF_COOKIES,
    CONF_METER_ID,
    CONF_METER_SERIAL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    POLL_HOUR,
    POLL_JITTER_MINUTES,
    STATISTIC_HOUR,
    STATISTIC_ID_MAINS,
    TRAILING_WINDOW_DAYS,
)
from .sew_client import (
    AccountIds,
    DailyUsage,
    SewAuthError,
    SewBusyError,
    SewClient,
    SewConnectionError,
    SewProtocolError,
)

_LOGGER = logging.getLogger(__name__)

# Seconds to wait before retrying when the portal reports it is throttling and gives no hint.
BUSY_RETRY_SECONDS = 15 * 60
# How far back to look for the last statistic row preceding a re-import window.
LOOKBACK_DAYS = 3660

type SewConfigEntry = ConfigEntry[SewCoordinator]


@dataclass(frozen=True)
class SewData:
    """State shared with the entities after each poll.

    Attributes:
        ids: Billing account and meter identifiers.
        latest: Most recent day with a non-zero reading, if any.
        total_litres: Running total of every litre imported into statistics.
        last_poll: When the portal was last read successfully.
        window: Every day fetched in the last poll, oldest first.
    """

    ids: AccountIds
    latest: DailyUsage | None
    total_litres: float
    last_poll: datetime
    window: tuple[DailyUsage, ...]


class SewCoordinator(DataUpdateCoordinator[SewData]):
    """Poll the portal once a day and keep long-term statistics up to date."""

    config_entry: SewConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SewConfigEntry, client: SewClient) -> None:
        """Initialise the coordinator.

        Args:
            hass: Home Assistant instance.
            entry: The config entry that owns this coordinator.
            client: Portal client whose session already holds the stored cookies.
        """
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=self._interval(entry))
        self.client = client
        self.ids = AccountIds(
            billing_account_id=entry.data[CONF_BILLING_ACCOUNT_ID],
            meter_id=entry.data[CONF_METER_ID],
            meter_serial=entry.data.get(CONF_METER_SERIAL),
        )

    # --------------------------------------------------------------- scheduling

    @staticmethod
    def _interval(entry: SewConfigEntry) -> timedelta:
        """Return the time until the next poll.

        At the default one-day interval the poll is pinned to ``POLL_HOUR`` local time so it runs when
        the previous day's readings are most likely available, plus a random offset of up to
        ``POLL_JITTER_MINUTES`` so installations do not all hit the portal in the same second; any
        other interval is used as given.
        """
        minutes = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        if minutes != DEFAULT_SCAN_INTERVAL:
            return timedelta(minutes=minutes)
        now = dt_util.now()
        next_run = now.replace(hour=POLL_HOUR, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run - now + timedelta(seconds=random.uniform(0, POLL_JITTER_MINUTES * 60))

    # ------------------------------------------------------------------ polling

    async def _async_update_data(self) -> SewData:
        """Fetch the trailing window (or the full backfill on first run) and store statistics."""
        yesterday = dt_util.now().date() - timedelta(days=1)
        first_run = await self._async_last_statistic_day() is None
        window_days = BACKFILL_DAYS if first_run else TRAILING_WINDOW_DAYS
        start = yesterday - timedelta(days=window_days - 1)
        try:
            data = await self._async_import(start, yesterday)
        finally:
            # Re-evaluate the delay to the next poll so the daily run stays pinned to POLL_HOUR.
            self.update_interval = self._interval(self.config_entry)
        return data

    async def async_import_from(self, start: date) -> None:
        """Import every day from ``start`` to yesterday, then notify entities.

        Args:
            start: First day to import.
        """
        yesterday = dt_util.now().date() - timedelta(days=1)
        if start > yesterday:
            raise ValueError("start date must be before today")
        self.async_set_updated_data(await self._async_import(start, yesterday))

    async def _async_import(self, start: date, end: date) -> SewData:
        """Fetch ``start``..``end`` from the portal, import statistics and build the shared state.

        Raises:
            ConfigEntryAuthFailed: If the stored session is no longer accepted, triggering reauth.
            UpdateFailed: If the portal is busy (with a short ``retry_after``), unreachable or answers
                unexpectedly.
        """
        try:
            if not await self.client.async_is_alive():
                raise ConfigEntryAuthFailed("Portal session expired; a new login code is required")
            usage = await self.client.async_fetch_usage(self.ids, start, end)
        except SewAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SewBusyError as err:
            # Salesforce throttles with an Apex error rather than a 429; back off briefly instead of
            # waiting for the next daily poll.
            raise UpdateFailed(str(err), retry_after=err.retry_after or BUSY_RETRY_SECONDS) from err
        except SewConnectionError as err:
            raise UpdateFailed(f"Cannot reach the portal: {err}") from err
        except SewProtocolError as err:
            raise UpdateFailed(f"Unexpected portal response: {err}") from err

        self._async_store_cookies()
        total = await self._async_import_statistics(usage)
        latest = next((day for day in reversed(usage) if day.available and day.litres > 0), None)
        _LOGGER.debug("Imported %d day(s) %s..%s; latest reading %s", len(usage), start, end, latest)
        return SewData(ids=self.ids, latest=latest, total_litres=total, last_poll=dt_util.utcnow(), window=tuple(usage))

    def _async_store_cookies(self) -> None:
        """Persist the (possibly refreshed) session cookies so a restart needs no new login."""
        cookies = self.client.export_cookies()
        if cookies != self.config_entry.data.get(CONF_COOKIES):
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, CONF_COOKIES: cookies}
            )

    # --------------------------------------------------------------- statistics

    @staticmethod
    def _metadata() -> StatisticMetaData:
        """Describe the mains-water external statistic used by the Energy dashboard."""
        return StatisticMetaData(
            has_sum=True,
            mean_type=StatisticMeanType.NONE,
            name="South East Water mains usage",
            source=DOMAIN,
            statistic_id=STATISTIC_ID_MAINS,
            unit_class=VolumeConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfVolume.LITERS,
        )

    async def _async_last_statistic_day(self) -> date | None:
        """Return the local day of the newest stored statistic, or ``None`` before the first import."""
        rows = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, STATISTIC_ID_MAINS, True, {"sum"}
        )
        if not (stats := rows.get(STATISTIC_ID_MAINS)):
            return None
        return dt_util.as_local(dt_util.utc_from_timestamp(stats[0]["start"])).date()

    @staticmethod
    def _row_start(day: date) -> datetime:
        """Return the timestamp a day's statistic row is stored under."""
        return dt_util.start_of_local_day(day) + timedelta(hours=STATISTIC_HOUR)

    async def _async_sum_before(self, day: date) -> float:
        """Return the running sum of the newest statistic row before ``day`` (0 if there is none)."""
        row_start = self._row_start(day)
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            row_start - timedelta(days=LOOKBACK_DAYS),
            row_start,
            {STATISTIC_ID_MAINS},
            # Hourly buckets so the cut-off is exact: a day bucket would start at midnight and swallow
            # the first row of the window itself.
            "hour",
            None,
            {"sum"},
        )
        if not (stats := rows.get(STATISTIC_ID_MAINS)):
            return 0.0
        return float(stats[-1].get("sum") or 0.0)

    async def _async_import_statistics(self, usage: list[DailyUsage]) -> float:
        """Write one statistic row per day and return the running total after the last day.

        Rows are keyed by their start time, so re-importing a day simply overwrites it; the running
        sum is rebuilt from the value recorded just before the window so corrections stay consistent.
        """
        if not usage:
            rows = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, STATISTIC_ID_MAINS, True, {"sum"}
            )
            stats = rows.get(STATISTIC_ID_MAINS)
            return float(stats[0].get("sum") or 0.0) if stats else 0.0
        running = await self._async_sum_before(usage[0].day)
        statistics: list[StatisticData] = []
        for day in usage:
            running += day.litres
            statistics.append(StatisticData(start=self._row_start(day.day), state=day.litres, sum=running))
        async_add_external_statistics(self.hass, self._metadata(), statistics)
        return running
