"""Number entities for the sensor's parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from mtdx62_modbus_library import SettingSpec

from . import Mtdx62ConfigEntry
from .coordinator import Mtdx62Coordinator
from .entity import Mtdx62Entity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class Mtdx62NumberDescription(NumberEntityDescription):
    """A parameter of the sensor, described by name and device class only.

    Limits, step and unit come from the library at runtime: they are the register
    map's business, not the integration's.
    """

    field: str
    bus: bool = False


NUMBERS: Final[tuple[Mtdx62NumberDescription, ...]] = (
    Mtdx62NumberDescription(
        key="detection_distance",
        translation_key="detection_distance",
        field="detection_distance",
        device_class=NumberDeviceClass.DISTANCE,
    ),
    Mtdx62NumberDescription(
        key="shielding_distance",
        translation_key="shielding_distance",
        field="shielding_distance",
        device_class=NumberDeviceClass.DISTANCE,
    ),
    Mtdx62NumberDescription(
        key="entry_indent",
        translation_key="entry_indent",
        field="entry_indent",
        device_class=NumberDeviceClass.DISTANCE,
    ),
    Mtdx62NumberDescription(
        key="entry_delay",
        translation_key="entry_delay",
        field="entry_delay",
        device_class=NumberDeviceClass.DURATION,
    ),
    Mtdx62NumberDescription(
        key="departure_delay",
        translation_key="departure_delay",
        field="departure_delay",
        device_class=NumberDeviceClass.DURATION,
    ),
    Mtdx62NumberDescription(
        key="trigger_sensitivity",
        translation_key="trigger_sensitivity",
        field="trigger_sensitivity",
    ),
    Mtdx62NumberDescription(
        key="maintain_sensitivity",
        translation_key="maintain_sensitivity",
        field="maintain_sensitivity",
    ),
    Mtdx62NumberDescription(
        key="light_threshold",
        translation_key="light_threshold",
        field="light_threshold",
        device_class=NumberDeviceClass.ILLUMINANCE,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Mtdx62ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the parameters; they stay out of the way until enabled."""
    coordinator = entry.runtime_data
    known = {spec.name for spec in coordinator.device.settings.writable_fields()}
    async_add_entities(
        Mtdx62Number(coordinator, description)
        for description in NUMBERS
        if description.field in known
    )


class Mtdx62Number(Mtdx62Entity, NumberEntity):
    """One writable parameter of the sensor."""

    entity_description: Mtdx62NumberDescription
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: Mtdx62Coordinator,
        description: Mtdx62NumberDescription,
    ) -> None:
        """Read the limits from the library and apply them to the entity."""
        super().__init__(coordinator, description.field)
        self.entity_description = description
        spec = self._spec(coordinator, description.field)
        self._attr_native_min_value = spec.minimum
        self._attr_native_max_value = spec.maximum
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit

    @staticmethod
    def _spec(coordinator: Mtdx62Coordinator, field: str) -> SettingSpec:
        """The library's description of this parameter."""
        for spec in coordinator.device.settings.writable_fields():
            if spec.name == field:
                return spec
        raise KeyError(field)  # pragma: no cover - the platform filters first

    @property
    def native_value(self) -> float | None:
        """The value the sensor confirmed, or what it reports after a poll."""
        value = getattr(self.coordinator.device.settings, self.entity_description.field)
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Write the value and let the coordinator explain a refusal."""
        await self.coordinator.async_write_setting(self.entity_description.field, value)
