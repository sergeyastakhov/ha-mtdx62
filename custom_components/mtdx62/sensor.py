"""Illuminance, target distance and the diagnostic sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import LIGHT_LUX, EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from mtdx62_modbus_library import DeviceStatus, Readings

from . import Mtdx62ConfigEntry
from .coordinator import Mtdx62Coordinator
from .entity import Mtdx62Entity

PARALLEL_UPDATES = 0

STATUS_KEYS: dict[DeviceStatus, str] = {
    DeviceStatus.SELF_CHECK_IN_PROGRESS: "self_check_in_progress",
    DeviceStatus.OK: "ok",
    DeviceStatus.SELF_TEST_FAILED: "self_test_failed",
    DeviceStatus.OTHER_FAULT: "other_fault",
    DeviceStatus.RADAR_FAULT: "radar_fault",
    DeviceStatus.RS485_FAULT: "rs485_fault",
    DeviceStatus.RADAR_AND_RS485_FAULT: "radar_and_rs485_fault",
}
UNKNOWN_CODE = "unknown_code"
STATUS_OPTIONS: list[str] = [*STATUS_KEYS.values(), UNKNOWN_CODE]


def _status_key(readings: Readings) -> str | None:
    """Show an undocumented health code as such instead of hiding it."""
    if readings.status_code is None:
        return None
    status = readings.status
    if status is None:
        return UNKNOWN_CODE
    return STATUS_KEYS[status]


def _distance_m(readings: Readings) -> float | None:
    """The library reports metres with a centimetre resolution; the entity keeps them."""
    return readings.distance


@dataclass(frozen=True, kw_only=True)
class Mtdx62SensorDescription(SensorEntityDescription):
    """A sensor of the device, reading one attribute of the library's model."""

    value_fn: Callable[[Readings], StateType]
    trust_required: bool = False
    """Hide the value unless the sensor reports a passed self-test."""


SENSORS: tuple[Mtdx62SensorDescription, ...] = (
    Mtdx62SensorDescription(
        key="illuminance",
        translation_key="illuminance",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
        trust_required=True,
        value_fn=lambda readings: readings.illuminance,
    ),
    Mtdx62SensorDescription(
        key="distance",
        translation_key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        trust_required=True,
        value_fn=_distance_m,
    ),
    Mtdx62SensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_status_key,
    ),
    Mtdx62SensorDescription(
        key="app_version",
        translation_key="app_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda readings: readings.app_version,
    ),
    Mtdx62SensorDescription(
        key="radar_version",
        translation_key="radar_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda readings: readings.radar_version,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Mtdx62ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the sensors of this entry."""
    async_add_entities(Mtdx62Sensor(entry.runtime_data, description) for description in SENSORS)


class Mtdx62Sensor(Mtdx62Entity, SensorEntity):
    """One measurement or diagnostic value of the sensor."""

    entity_description: Mtdx62SensorDescription

    def __init__(
        self,
        coordinator: Mtdx62Coordinator,
        description: Mtdx62SensorDescription,
    ) -> None:
        """Create the sensor from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Measurements are hidden unless the sensor vouches for them."""
        if self.entity_description.trust_required and not self.measurements_trusted:
            return False
        return super().available

    @property
    def native_value(self) -> StateType:
        """Read the value out of the library's model."""
        return self.entity_description.value_fn(self.coordinator.data)
