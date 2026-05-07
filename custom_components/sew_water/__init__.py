"""Water Portal integration for Home Assistant (South East Water / Yarra Valley Water)."""

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
    CONF_PORTAL,
    CONF_SCAN_INTERVAL,
    COORDINATOR,
    DEFAULT_PORTAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PORTAL_OPTIONS,
)
from .coordinator import WaterPortalCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

SERVICE_IMPORT_FROM_DATE = "import_from_date"
SERVICE_FORCE_IMPORT     = "force_import"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Water Portal from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    data   = {**entry.data, **entry.options}
    portal = data.get(CONF_PORTAL, DEFAULT_PORTAL)

    session = async_get_clientsession(hass)
    client  = SEWBrowserlessClient(
        session            = session,
        browserless_url    = data[CONF_BROWSERLESS_URL],
        browserless_token  = data.get(CONF_BROWSERLESS_TOKEN, ""),
        username           = data[CONF_USERNAME],
        password           = data[CONF_PASSWORD],
        portal             = portal,
        billing_account_id = data.get(CONF_BILLING_ACCOUNT_ID, ""),
        meter_id           = data.get(CONF_METER_ID, ""),
    )

    scan_interval = timedelta(
        minutes=int(data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    )

    coordinator = WaterPortalCoordinator(hass, client, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {COORDINATOR: coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------
    async def handle_import_from_date(call: ServiceCall) -> None:
        raw = call.data.get("start_date")
        if not raw:
            _LOGGER.error("sew_water.import_from_date requires 'start_date'")
            return
        try:
            start = date.fromisoformat(str(raw))
        except ValueError:
            _LOGGER.error("Invalid start_date '%s'; expected YYYY-MM-DD", raw)
            return
        await coordinator.force_import_from_date(start)

    async def handle_force_import(_call: ServiceCall) -> None:
        await coordinator.async_refresh()

    if not hass.services.has_service(DOMAIN, SERVICE_IMPORT_FROM_DATE):
        hass.services.async_register(DOMAIN, SERVICE_IMPORT_FROM_DATE, handle_import_from_date)
    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_IMPORT):
        hass.services.async_register(DOMAIN, SERVICE_FORCE_IMPORT, handle_force_import)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_IMPORT_FROM_DATE)
        hass.services.async_remove(DOMAIN, SERVICE_FORCE_IMPORT)
    return unload_ok
