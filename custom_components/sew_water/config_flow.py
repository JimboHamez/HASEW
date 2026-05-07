"""Config flow for South East Water integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .browserless_client import BrowserlessError, SEWBrowserlessClient
from .const import (
    CONF_BILLING_ACCOUNT_ID,
    CONF_BROWSERLESS_TOKEN,
    CONF_BROWSERLESS_URL,
    CONF_METER_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_BROWSERLESS_URL): str,
        vol.Optional(CONF_BROWSERLESS_TOKEN, default=""): str,
        vol.Optional(CONF_BILLING_ACCOUNT_ID, default=""): str,
        vol.Optional(CONF_METER_ID, default=""): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            int, vol.Range(min=60)
        ),
    }
)


class SEWWaterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for South East Water."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate Browserless connectivity before creating the entry
            session = async_get_clientsession(self.hass)
            client = SEWBrowserlessClient(
                session=session,
                browserless_url=user_input[CONF_BROWSERLESS_URL],
                browserless_token=user_input.get(CONF_BROWSERLESS_TOKEN, ""),
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                billing_account_id=user_input.get(CONF_BILLING_ACCOUNT_ID, ""),
                meter_id=user_input.get(CONF_METER_ID, ""),
            )

            reachable = await client.test_connection()
            if not reachable:
                errors["base"] = "cannot_connect_browserless"
            else:
                await self.async_set_unique_id(
                    f"{DOMAIN}_{user_input[CONF_USERNAME]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"South East Water ({user_input[CONF_USERNAME]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={
                "browserless_docs": "http://<browserless-host>:3000/config"
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SEWWaterOptionsFlow:
        """Return the options flow handler."""
        return SEWWaterOptionsFlow(config_entry)


class SEWWaterOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the South East Water integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options or self._config_entry.data

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
