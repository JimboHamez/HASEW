"""South East Water custom integration for Home Assistant."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .browserless_client import SEWBrowserlessClient
from .const import (
    CONF_BILLING_ACCOUNT_ID,
    CONF_BROWSERLESS_TOKEN,
    CONF_BROWSERLESS_URL,
    CONF_METER_ID,
    CONF_SCAN_INTERVAL,
    COORDINATOR,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import SEWDataCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

# ---------------------------------------------------------------------------
# Service names
# ---------------------------------------------------------------------------
SERVICE_IMPORT_FROM_DATE = "import_from_date"
SERVICE_FORCE_IMPORT = "force_import"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up South East Water from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    data = {**entry.data, **entry.options}

    session = async_get_clientsession(hass)
    client = SEWBrowserlessClient(
        session=session,
        browserless_url=data[CONF_BROWSERLESS_URL],
        browserless_token=data.get(CONF_BROWSERLESS_TOKEN, ""),
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        billing_account_id=data.get(CONF_BILLING_ACCOUNT_ID, ""),
        meter_id=data.get(CONF_METER_ID, ""),
    )

    scan_interval_minutes = int(data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    scan_interval = timedelta(minutes=scan_interval_minutes)

    coordinator = SEWDataCoordinator(hass, client, scan_interval)

    # Perform first refresh (will not raise if it fails – logged as warning)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {COORDINATOR: coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ------------------------------------------------------------------
    # Register services
    # ------------------------------------------------------------------
    async def handle_import_from_date(call: ServiceCall) -> None:
        """Service: sew_water.import_from_date  (start_date: YYYY-MM-DD)."""
        raw_date = call.data.get("start_date")
        if not raw_date:
            _LOGGER.error("sew_water.import_from_date requires 'start_date'")
            return
        try:
            start = date.fromisoformat(str(raw_date))
        except ValueError:
            _LOGGER.error("Invalid start_date format '%s'; expected YYYY-MM-DD", raw_date)
            return
        await coordinator.force_import_from_date(start)

    async def handle_force_import(call: ServiceCall) -> None:
        """Service: sew_water.force_import  – refreshes immediately."""
        await coordinator.async_refresh()

    if not hass.services.has_service(DOMAIN, SERVICE_IMPORT_FROM_DATE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_IMPORT_FROM_DATE,
            handle_import_from_date,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_IMPORT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCE_IMPORT,
            handle_force_import,
        )

    # Update options listener
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update – reload the integration."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # Only remove services when there are no more loaded entries for this domain
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_IMPORT_FROM_DATE)
        hass.services.async_remove(DOMAIN, SERVICE_FORCE_IMPORT)

    return unload_ok
