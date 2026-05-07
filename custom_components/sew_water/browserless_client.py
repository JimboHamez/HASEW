"""Client for communicating with Browserless Chrome to scrape water portal data."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any

import aiohttp

from .const import (
    DATA_DATE,
    DATA_MAINS,
    DATA_RECYCLED,
    DEFAULT_PORTAL,
    PORTAL_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

# Path to the Puppeteer JS script bundled with this integration
_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "browserless_script.js")

# Browserless timeout: base 90 s + 2 s per day requested (batch call is one
# round-trip but the page still has to log in and navigate first).
_BASE_TIMEOUT_SECS = 90
_SECS_PER_DAY      = 2


class BrowserlessError(Exception):
    """Raised when Browserless returns an error."""


class SEWBrowserlessClient:
    """Async wrapper around the Browserless /function endpoint."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        browserless_url: str,
        browserless_token: str,
        username: str,
        password: str,
        portal: str = DEFAULT_PORTAL,
        billing_account_id: str = "",
        meter_id: str = "",
    ) -> None:
        self._session            = session
        self._browserless_url    = browserless_url.rstrip("/")
        self._browserless_token  = browserless_token
        self._username           = username
        self._password           = password
        self._portal             = portal if portal in PORTAL_OPTIONS else DEFAULT_PORTAL
        self._billing_account_id = billing_account_id
        self._meter_id           = meter_id

        # Load the JS script once at construction time
        with open(_SCRIPT_PATH, "r", encoding="utf-8") as fh:
            self._js_script = fh.read()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def billing_account_id(self) -> str:
        return self._billing_account_id

    @property
    def meter_id(self) -> str:
        return self._meter_id

    @property
    def portal(self) -> str:
        return self._portal

    @property
    def attribution(self) -> str:
        return PORTAL_OPTIONS[self._portal].get("attribution", "Data provided by water utility")

    async def test_connection(self) -> bool:
        """Return True if the Browserless instance is reachable."""
        try:
            async with self._session.get(
                f"{self._browserless_url}/config",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Browserless connection test failed: %s", exc)
            return False

    async def get_usage_range(
        self, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """
        Fetch usage for start_date..end_date in a single batched Browserless call.
        Returns the raw list of per-day dicts (each has 'date' + 'data' or 'error').
        """
        days = (end_date - start_date).days + 1
        result = await self._run_function(
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
            num_days=days,
        )

        # Cache any newly discovered account/meter IDs
        if not self._billing_account_id and result.get("billingAccountId"):
            self._billing_account_id = result["billingAccountId"]
            _LOGGER.info("Discovered billingAccountId: %s", self._billing_account_id)
        if not self._meter_id and result.get("meterId"):
            self._meter_id = result["meterId"]
            _LOGGER.info("Discovered meterId: %s", self._meter_id)

        # JS script returns { ..., usage: [ {date, data} | {date, error} ] }
        return result.get("usage", [])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_endpoint(self) -> str:
        endpoint = f"{self._browserless_url}/function"
        if self._browserless_token:
            endpoint += f"?token={self._browserless_token}"
        return endpoint

    async def _run_function(
        self,
        start_date_str: str,
        end_date_str: str,
        num_days: int = 1,
    ) -> dict[str, Any]:
        """POST the Puppeteer script to Browserless and return parsed JSON."""

        timeout_secs = _BASE_TIMEOUT_SECS + (_SECS_PER_DAY * num_days)

        payload = {
            "code": self._js_script,
            "context": {
                "username":         self._username,
                "password":         self._password,
                "portal":           self._portal,
                "billingAccountId": self._billing_account_id,
                "meterId":          self._meter_id,
                "startDate":        start_date_str,
                "endDate":          end_date_str,
            },
        }

        _LOGGER.debug(
            "Calling Browserless /function [%s] for %s → %s (%d days, timeout %ds)",
            self._portal,
            start_date_str,
            end_date_str,
            num_days,
            timeout_secs,
        )

        endpoint = self._build_endpoint()
        try:
            async with self._session.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=timeout_secs),
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


# ---------------------------------------------------------------------------
# Parse / normalise raw usage records returned by the JS script
# ---------------------------------------------------------------------------

def parse_usage_records(raw_usage: list[dict]) -> list[dict[str, Any]]:
    """
    Normalise the raw per-day entries from the Aura batch response into a list
    of dicts with keys: date (datetime.date), mains (float L), recycled (float L).

    Each entry in raw_usage has the shape:
        { "date": "YYYY-MM-DD", "data": <Aura returnValue> }
      or
        { "date": "YYYY-MM-DD", "error": "<message>" }

    The Aura returnValue for getUsageData is typically a list of hourly interval
    records; we sum all hours to produce a daily total.
    """
    normalised: list[dict[str, Any]] = []

    for entry in raw_usage:
        if "error" in entry:
            _LOGGER.warning(
                "Skipping errored usage entry for %s: %s",
                entry.get("date"),
                entry["error"],
            )
            continue

        date_str: str = entry.get("date", "")
        try:
            reading_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            _LOGGER.warning("Could not parse date '%s' in usage entry", date_str)
            continue

        return_value    = entry.get("data")
        mains_litres    = 0.0
        recycled_litres = 0.0

        if return_value is None:
            _LOGGER.debug("No returnValue for date %s", date_str)

        elif isinstance(return_value, list):
            # List of hourly interval records – sum them
            for interval in return_value:
                if isinstance(interval, dict):
                    mains_litres    += _extract_volume(interval, ("mainsConsumption", "mains", "consumption", "usage"))
                    recycled_litres += _extract_volume(interval, ("recycledConsumption", "recycled"))

        elif isinstance(return_value, dict):
            # Check for a nested list under known wrapper keys
            for list_key in ("usageData", "data", "intervals", "hours"):
                if list_key in return_value and isinstance(return_value[list_key], list):
                    for interval in return_value[list_key]:
                        if isinstance(interval, dict):
                            mains_litres    += _extract_volume(interval, ("mainsConsumption", "mains", "consumption", "usage"))
                            recycled_litres += _extract_volume(interval, ("recycledConsumption", "recycled"))
                    break
            else:
                # Flat daily aggregate dict
                mains_litres    = _extract_volume(return_value, ("mainsConsumption", "mains", "totalConsumption", "consumption", "usage"))
                recycled_litres = _extract_volume(return_value, ("recycledConsumption", "recycled"))

        normalised.append(
            {
                DATA_DATE:     reading_date,
                DATA_MAINS:    mains_litres,
                DATA_RECYCLED: recycled_litres,
            }
        )

    normalised.sort(key=lambda r: r[DATA_DATE])
    return normalised


def _extract_volume(record: dict, keys: tuple) -> float:
    """Return the first numeric value found under any of the candidate keys."""
    for key in keys:
        if key in record:
            try:
                return float(record[key])
            except (TypeError, ValueError):
                pass
    return 0.0
