"""Config flow for Water Portal (South East Water / Yarra Valley Water) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .browserless_client import SEWBrowserlessClient
from .const import (
    CONF_BILLING_ACCOUNT_ID,
    CONF_BROWSERLESS_TOKEN,
    CONF_BROWSERLESS_URL,
    CONF_METER_ID,
    CONF_PORTAL,
    CONF_SCAN_INTERVAL,
    DEFAULT_PORTAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PORTAL_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

# Build the portal selector options from PORTAL_OPTIONS so const.py is the
# single source of truth – no duplication here.
_PORTAL_SELECT_OPTIONS = [
    SelectOptionDict(value=key, label=cfg["label"])
    for key, cfg in PORTAL_OPTIONS.items()
]


def _build_user_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_PORTAL, default=d.get(CONF_PORTAL, DEFAULT_PORTAL)): SelectSelector(
                SelectSelectorConfig(
                    options=_PORTAL_SELECT_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=d.get(CONF_PASSWORD, "")): str,
            vol.Required(CONF_BROWSERLESS_URL, default=d.get(CONF_BROWSERLESS_URL, "")): str,
            vol.Optional(CONF_BROWSERLESS_TOKEN, default=d.get(CONF_BROWSERLESS_TOKEN, "")): str,
            vol.Optional(CONF_BILLING_ACCOUNT_ID, default=d.get(CONF_BILLING_ACCOUNT_ID, "")): str,
            vol.Optional(CONF_METER_ID, default=d.get(CONF_METER_ID, "")): str,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=d.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(int, vol.Range(min=60)),
        }
    )


class WaterPortalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Water Portal integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = SEWBrowserlessClient(
                session=session,
                browserless_url=user_input[CONF_BROWSERLESS_URL],
                browserless_token=user_input.get(CONF_BROWSERLESS_TOKEN, ""),
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                portal=user_input.get(CONF_PORTAL, DEFAULT_PORTAL),
                billing_account_id=user_input.get(CONF_BILLING_ACCOUNT_ID, ""),
                meter_id=user_input.get(CONF_METER_ID, ""),
            )

            reachable = await client.test_connection()
            if not reachable:
                errors["base"] = "cannot_connect_browserless"
            else:
                portal_key = user_input.get(CONF_PORTAL, DEFAULT_PORTAL)
                portal_label = PORTAL_OPTIONS.get(portal_key, {}).get("label", portal_key)

                await self.async_set_unique_id(
                    f"{DOMAIN}_{portal_key}_{user_input[CONF_USERNAME]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{portal_label} ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_user_schema(),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> WaterPortalOptionsFlow:
        """Return the options flow handler."""
        return WaterPortalOptionsFlow(config_entry)


class WaterPortalOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the Water Portal integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(int, vol.Range(min=60)),
                vol.Optional(
                    CONF_BILLING_ACCOUNT_ID,
                    default=current.get(CONF_BILLING_ACCOUNT_ID, ""),
                ): str,
                vol.Optional(
                    CONF_METER_ID,
                    default=current.get(CONF_METER_ID, ""),
                ): str,
                vol.Optional(
                    CONF_BROWSERLESS_TOKEN,
                    default=current.get(CONF_BROWSERLESS_TOKEN, ""),
                ): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
