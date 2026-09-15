"""Tests for the config entry diagnostics."""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.sew_water.const import CONF_BILLING_ACCOUNT_ID, CONF_COOKIES, CONF_METER_ID, CONF_METER_SERIAL

from .conftest import METER_SERIAL, FakeClient

REDACTED = "**REDACTED**"


async def test_diagnostics_redacts_secrets_and_identifiers(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_integration: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    result = await get_diagnostics_for_config_entry(hass, hass_client, setup_integration)

    entry_data = result["entry"]["data"]
    for key in (CONF_BILLING_ACCOUNT_ID, CONF_COOKIES, CONF_METER_ID, CONF_PASSWORD, CONF_USERNAME):
        assert entry_data[key] == REDACTED
    # The serial is left visible; it appears on the meter itself and is useful when reporting issues.
    assert entry_data[CONF_METER_SERIAL] == METER_SERIAL
    assert result["entry"]["options"] == {}

    coordinator = result["coordinator"]
    assert coordinator["last_poll"] is not None
    assert coordinator["latest"]["litres"] == 240
    assert coordinator["total_litres"] > 0
    assert coordinator["window_days"] > 0
    assert coordinator["update_interval"]


async def test_diagnostics_without_data(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_integration: MockConfigEntry,
) -> None:
    """The coordinator section degrades gracefully when no poll has succeeded."""
    setup_integration.runtime_data.data = None
    result = await get_diagnostics_for_config_entry(hass, hass_client, setup_integration)
    assert result["coordinator"] == {
        "last_poll": None,
        "latest": None,
        "total_litres": None,
        "update_interval": result["coordinator"]["update_interval"],
        "window_days": 0,
    }
