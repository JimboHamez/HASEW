"""Sensor platform for South East Water."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
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

from .const import ATTRIBUTION, COORDINATOR, DOMAIN
from .coordinator import SEWDataCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SEWSensorEntityDescription(SensorEntityDescription):
    """Describes a South East Water sensor."""

    data_key: str = ""


SENSOR_DESCRIPTIONS: tuple[SEWSensorEntityDescription, ...] = (
    SEWSensorEntityDescription(
        key="last_mains",
        name="Last Mains Water Reading",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water",
        data_key="last_mains",
    ),
    SEWSensorEntityDescription(
        key="last_recycled",
        name="Last Recycled Water Reading",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-sync",
        data_key="last_recycled",
    ),
    SEWSensorEntityDescription(
        key="last_reading_date",
        name="Last Water Reading Date",
        icon="mdi:calendar-check",
        data_key="last_date",
    ),
    SEWSensorEntityDescription(
        key="billing_account_id",
        name="SEW Billing Account ID",
        icon="mdi:account",
        data_key="billing_account_id",
    ),
    SEWSensorEntityDescription(
        key="meter_id",
        name="SEW Meter ID",
        icon="mdi:counter",
        data_key="meter_id",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up South East Water sensors from a config entry."""
    coordinator: SEWDataCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    async_add_entities(
        SEWSensorEntity(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class SEWSensorEntity(CoordinatorEntity[SEWDataCoordinator], SensorEntity):
    """A sensor reporting a South East Water data point."""

    _attr_attribution = ATTRIBUTION
    entity_description: SEWSensorEntityDescription

    def __init__(
        self,
        coordinator: SEWDataCoordinator,
        entry: ConfigEntry,
        description: SEWSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="South East Water",
            manufacturer="South East Water",
            model="Digital Water Meter",
            entry_type=None,
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value from coordinator data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.data_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        if self.coordinator.data is None:
            return {}
        return {
            "last_fetch": self.coordinator.data.get("last_fetch"),
            "records_fetched": self.coordinator.data.get("records_fetched"),
        }
