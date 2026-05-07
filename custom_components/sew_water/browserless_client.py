"""Client for communicating with Browserless Chrome to scrape the SEW portal."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

import aiohttp

from .const import (
    DATA_BILLING_ACCOUNT_ID,
    DATA_DATE,
    DATA_MAINS,
    DATA_METER_ID,
    DATA_RECYCLED,
    SEW_BASE_URL,
)

_LOGGER = logging.getLogger(__name__)

# Path to the Puppeteer JS script bundled with this integration
_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "browserless_script.js")


class BrowserlessError(Exception):
    """Raised when Browserless returns an error."""


class SEWBrowserlessClient:
    """Thin async wrapper around the Browserless /function endpoint."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        browserless_url: str,
        browserless_token: str,
        username: str,
        password: str,
        billing_account_id: str = "",
        meter_id: str = "",
    ) -> None:
        self._session = session
        self._browserless_url = browserless_url.rstrip("/")
        self._browserless_token = browserless_token
        self._username = username
        self._password = password
        self._billing_account_id = billing_account_id
        self._meter_id = meter_id

        # Load the JS script once at construction time
        with open(_SCRIPT_PATH, "r", encoding="utf-8") as fh:
            self._js_script = fh.read()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def test_connection(self) -> bool:
        """Return True if the Browserless instance is reachable."""
        try:
            async with self._session.get(
                f"{self._browserless_url}/config", timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                return resp.status == 200
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Browserless connection test failed: %s", exc)
            return False

    async def get_usage_for_date(self, target_date: date) -> dict[str, Any]:
        """Return usage data for a single date (YYYY-MM-DD)."""
        date_str = target_date.strftime("%Y-%m-%d")
        return await self._run_function(date_str, date_str)

    async def get_usage_range(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """
        Call the Browserless script for the given date range and return the raw
        list of per-day result dicts (each has 'date' and 'data' / 'error' keys).
        """
        result = await self._run_function(
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
        )

        # Cache any newly discovered account/meter IDs
        if not self._billing_account_id and result.get("billingAccountId"):
            self._billing_account_id = result["billingAccountId"]
            _LOGGER.info("Discovered billingAccountId: %s", self._billing_account_id)
        if not self._meter_id and result.get("meterId"):
            self._meter_id = result["meterId"]
            _LOGGER.info("Discovered meterId: %s", self._meter_id)

        # The JS script returns { ..., usage: [ {date, data} | {date, error} ] }
        return result.get("usage", [])

    @property
    def billing_account_id(self) -> str:
        return self._billing_account_id

    @property
    def meter_id(self) -> str:
        return self._meter_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_endpoint(self) -> str:
        """Build the Browserless /function endpoint URL, including token if set."""
        endpoint = f"{self._browserless_url}/function"
        if self._browserless_token:
            endpoint += f"?token={self._browserless_token}"
        return endpoint

    async def _run_function(
        self, start_date_str: str, end_date_str: str
    ) -> dict[str, Any]:
        """POST the Puppeteer script to Browserless and return parsed JSON."""

        payload = {
            "code": self._js_script,
            "context": {
                "username": self._username,
                "password": self._password,
                "billingAccountId": self._billing_account_id,
                "meterId": self._meter_id,
                "startDate": start_date_str,
                "endDate": end_date_str,
            },
        }

        endpoint = self._build_endpoint()
        _LOGGER.debug(
            "Calling Browserless /function for dates %s → %s",
            start_date_str,
            end_date_str,
        )

        try:
            async with self._session.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise BrowserlessError(
                        f"Browserless returned HTTP {resp.status}: {text[:300]}"
                    )
                result: dict[str, Any] = await resp.json()

        except aiohttp.ClientError as exc:
            raise BrowserlessError(f"HTTP error calling Browserless: {exc}") from exc

        if "error" in result:
            raise BrowserlessError(f"Script error from Browserless: {result['error']}")

        return result


def parse_usage_records(raw_usage: list[dict]) -> list[dict[str, Any]]:
    """
    Normalise the raw usage entries returned by the Aura script into a list of
    dicts with keys: date, mains (L), recycled (L).

    Each entry in raw_usage has the shape returned by the JS script:
        {
          "date": "YYYY-MM-DD",
          "data": <returnValue from MysewUsageBillingGraphController.getUsageData>
        }

    The returnValue is typically a dict or list.  The portal returns hourly
    interval data; we sum all hours for the day to get a daily total.
    """
    normalised: list[dict[str, Any]] = []

    for entry in raw_usage:
        # Skip entries that the JS script marked as errors
        if "error" in entry:
            _LOGGER.warning("Skipping errored usage entry for %s: %s", entry.get("date"), entry["error"])
            continue

        date_str: str = entry.get("date", "")
        try:
            reading_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            _LOGGER.warning("Could not parse date '%s' in usage entry", date_str)
            continue

        return_value = entry.get("data")

        mains_litres    = 0.0
        recycled_litres = 0.0

        if return_value is None:
            _LOGGER.debug("No returnValue for date %s", date_str)
        elif isinstance(return_value, list):
            # List of hourly interval records – sum them up
            for interval in return_value:
                if not isinstance(interval, dict):
                    continue
                mains_litres    += _extract_volume(interval, ("mainsConsumption", "mains", "consumption", "usage"))
                recycled_litres += _extract_volume(interval, ("recycledConsumption", "recycled"))
        elif isinstance(return_value, dict):
            # Some API versions return a single-day aggregate dict
            # It may also wrap the list under a key like "usageData" or "data"
            for list_key in ("usageData", "data", "intervals", "hours"):
                if list_key in return_value and isinstance(return_value[list_key], list):
                    for interval in return_value[list_key]:
                        if isinstance(interval, dict):
                            mains_litres    += _extract_volume(interval, ("mainsConsumption", "mains", "consumption", "usage"))
                            recycled_litres += _extract_volume(interval, ("recycledConsumption", "recycled"))
                    break
            else:
                # Flat aggregate dict
                mains_litres    = _extract_volume(return_value, ("mainsConsumption", "mains", "totalConsumption", "consumption", "usage"))
                recycled_litres = _extract_volume(return_value, ("recycledConsumption", "recycled"))

        normalised.append(
            {
                DATA_DATE: reading_date,
                DATA_MAINS: mains_litres,
                DATA_RECYCLED: recycled_litres,
            }
        )

    normalised.sort(key=lambda r: r[DATA_DATE])
    return normalised


def _extract_volume(record: dict, keys: tuple) -> float:
    """Try a list of candidate keys and return the first numeric value found."""
    for key in keys:
        if key in record:
            try:
                return float(record[key])
            except (TypeError, ValueError):
                pass
    return 0.0
