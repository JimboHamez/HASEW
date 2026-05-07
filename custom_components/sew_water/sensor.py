"""Sensor platform for Water Portal (South East Water / Yarra Valley Water)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR, DOMAIN, PORTAL_OPTIONS, DEFAULT_PORTAL
from .coordinator import WaterPortalCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WaterSensorEntityDescription(SensorEntityDescription):
    data_key: str = ""


SENSOR_DESCRIPTIONS: tuple[WaterSensorEntityDescription, ...] = (
    WaterSensorEntityDescription(
        key="last_mains",
        name="Last Mains Water Reading",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water",
        data_key="last_mains",
    ),
    WaterSensorEntityDescription(
        key="last_recycled",
        name="Last Recycled Water Reading",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-sync",
        data_key="last_recycled",
    ),
    WaterSensorEntityDescription(
        key="last_reading_date",
        name="Last Water Reading Date",
        icon="mdi:calendar-check",
        data_key="last_date",
    ),
    WaterSensorEntityDescription(
        key="billing_account_id",
        name="Billing Account ID",
        icon="mdi:account",
        data_key="billing_account_id",
    ),
    WaterSensorEntityDescription(
        key="meter_id",
        name="Meter ID",
        icon="mdi:counter",
        data_key="meter_id",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WaterPortalCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    async_add_entities(
        WaterSensorEntity(coordinator, entry, desc) for desc in SENSOR_DESCRIPTIONS
    )


class WaterSensorEntity(CoordinatorEntity[WaterPortalCoordinator], SensorEntity):
    """A sensor reporting a water portal data point."""

    entity_description: WaterSensorEntityDescription

    def __init__(
        self,
        coordinator: WaterPortalCoordinator,
        entry: ConfigEntry,
        description: WaterSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id    = f"{entry.entry_id}_{description.key}"

        portal_key   = entry.data.get("portal", DEFAULT_PORTAL)
        portal_label = PORTAL_OPTIONS.get(portal_key, {}).get("label", "Water Portal")

        self._attr_attribution = PORTAL_OPTIONS.get(portal_key, {}).get(
            "attribution", "Data provided by water utility"
        )
        self._attr_device_info = DeviceInfo(
            identifiers = {(DOMAIN, entry.entry_id)},
            name        = portal_label,
            manufacturer= portal_label,
            model       = "Digital Water Meter",
        )

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.data_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        return {
            "portal":          self.coordinator.data.get("portal"),
            "last_fetch":      self.coordinator.data.get("last_fetch"),
            "records_fetched": self.coordinator.data.get("records_fetched"),
        }
