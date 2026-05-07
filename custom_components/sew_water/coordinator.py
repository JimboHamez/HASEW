"""DataUpdateCoordinator for the Water Portal integration."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .browserless_client import BrowserlessError, SEWBrowserlessClient, parse_usage_records
from .const import DATA_DATE, DATA_MAINS, DATA_RECYCLED, DOMAIN

_LOGGER = logging.getLogger(__name__)

STATISTIC_ID_MAINS    = f"{DOMAIN}:water_usage_mains"
STATISTIC_ID_RECYCLED = f"{DOMAIN}:water_usage_recycled"


class WaterPortalCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch daily water usage and insert into HA long-term statistics."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SEWBrowserlessClient,
        scan_interval: timedelta,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=scan_interval)
        self._client = client

    @property
    def client(self) -> SEWBrowserlessClient:
        return self._client

    async def force_import_from_date(self, start_date: date) -> None:
        """Backfill data from start_date up to yesterday."""
        yesterday = date.today() - timedelta(days=1)
        if start_date > yesterday:
            _LOGGER.warning("force_import_from_date: start_date %s is in the future", start_date)
            return
        await self._import_range(start_date, yesterday)

    # ------------------------------------------------------------------
    # DataUpdateCoordinator protocol
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            start_date = await self._determine_start_date()
            yesterday  = date.today() - timedelta(days=1)

            if start_date > yesterday:
                _LOGGER.debug("No new dates to fetch (start=%s, yesterday=%s)", start_date, yesterday)
                return self.data or {}

            records = await self._import_range(start_date, yesterday)
            return {
                "last_fetch":         datetime.now().isoformat(),
                "records_fetched":    len(records),
                "billing_account_id": self._client.billing_account_id,
                "meter_id":           self._client.meter_id,
                "portal":             self._client.portal,
                "last_date":          records[-1][DATA_DATE].isoformat() if records else None,
                "last_mains":         records[-1][DATA_MAINS]    if records else None,
                "last_recycled":      records[-1][DATA_RECYCLED] if records else None,
            }

        except BrowserlessError as exc:
            raise UpdateFailed(f"Browserless error: {exc}") from exc
        except Exception as exc:
            _LOGGER.exception("Unexpected error during water portal update")
            raise UpdateFailed(f"Unexpected error: {exc}") from exc

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _determine_start_date(self) -> date:
        """Return the day after the last stored statistic, or 90 days ago."""
        try:
            last_stats = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics,
                self.hass,
                1,
                STATISTIC_ID_MAINS,
                True,
                {"sum"},
            )
            if last_stats and STATISTIC_ID_MAINS in last_stats:
                last_ts   = last_stats[STATISTIC_ID_MAINS][0]["start"]
                last_date = datetime.fromtimestamp(last_ts, tz=dt_util.UTC).date()
                _LOGGER.debug("Last statistic date = %s", last_date)
                return last_date + timedelta(days=1)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Could not read last statistics: %s", exc)

        return date.today() - timedelta(days=90)

    async def _import_range(self, start_date: date, end_date: date) -> list[dict]:
        """Fetch a date range in a single batched Browserless call and store statistics."""
        num_days = (end_date - start_date).days + 1
        _LOGGER.info(
            "Fetching %d day(s) of usage [%s → %s] via Browserless (%s)",
            num_days, start_date, end_date, self._client.portal,
        )

        raw     = await self._client.get_usage_range(start_date, end_date)
        records = parse_usage_records(raw)

        if not records:
            _LOGGER.warning("No usage records returned for %s → %s", start_date, end_date)
            return []

        await self._insert_statistics(records)
        return records

    async def _insert_statistics(self, records: list[dict]) -> None:
        """Insert parsed records as HA long-term statistics."""
        existing_sum_mains    = await self._get_last_sum(STATISTIC_ID_MAINS)
        existing_sum_recycled = await self._get_last_sum(STATISTIC_ID_RECYCLED)

        running_mains    = existing_sum_mains
        running_recycled = existing_sum_recycled
        mains_stats:    list[StatisticData] = []
        recycled_stats: list[StatisticData] = []

        for record in records:
            record_date: date  = record[DATA_DATE]
            mains:       float = record[DATA_MAINS]
            recycled:    float = record[DATA_RECYCLED]

            local_dt = datetime.combine(record_date, datetime.min.time()).replace(
                hour=11, minute=0, second=0, microsecond=0
            )
            utc_dt = dt_util.as_utc(dt_util.as_local(local_dt))

            running_mains    += mains
            running_recycled += recycled

            mains_stats.append(StatisticData(start=utc_dt, state=mains,    sum=running_mains))
            recycled_stats.append(StatisticData(start=utc_dt, state=recycled, sum=running_recycled))

        portal_label = self._client.attribution

        mains_meta = StatisticMetaData(
            has_mean=False, has_sum=True,
            name=f"Water Usage Mains ({portal_label})",
            source=DOMAIN,
            statistic_id=STATISTIC_ID_MAINS,
            unit_of_measurement=UnitOfVolume.LITERS,
        )
        recycled_meta = StatisticMetaData(
            has_mean=False, has_sum=True,
            name=f"Water Usage Recycled ({portal_label})",
            source=DOMAIN,
            statistic_id=STATISTIC_ID_RECYCLED,
            unit_of_measurement=UnitOfVolume.LITERS,
        )

        if mains_stats:
            async_add_external_statistics(self.hass, mains_meta, mains_stats)
            _LOGGER.info("Inserted %d mains statistics", len(mains_stats))
        if recycled_stats:
            async_add_external_statistics(self.hass, recycled_meta, recycled_stats)
            _LOGGER.info("Inserted %d recycled statistics", len(recycled_stats))

    async def _get_last_sum(self, statistic_id: str) -> float:
        try:
            last = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, True, {"sum"},
            )
            if last and statistic_id in last:
                return float(last[statistic_id][0].get("sum") or 0.0)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Could not retrieve last sum for %s: %s", statistic_id, exc)
        return 0.0
