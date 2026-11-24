"""Presence: the reason this integration exists."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Mtdx62ConfigEntry
from .coordinator import Mtdx62Coordinator
from .entity import Mtdx62Entity

# The coordinator polls; entities themselves never talk to the bus.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Mtdx62ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the presence sensor of this entry."""
    async_add_entities([Mtdx62PresenceSensor(entry.runtime_data)])


class Mtdx62PresenceSensor(Mtdx62Entity, BinarySensorEntity):
    """Whether a person is in the room, including someone sitting still."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_translation_key = "presence"

    def __init__(self, coordinator: Mtdx62Coordinator) -> None:
        """Create the presence entity."""
        super().__init__(coordinator, "presence")

    @property
    def available(self) -> bool:
        """Hide the presence flag while the sensor does not vouch for it."""
        return super().available and self.measurements_trusted

    @property
    def is_on(self) -> bool | None:
        """Return the state the sensor reported, without any local filtering."""
        presence = self.coordinator.data.presence
        return None if presence is None else bool(presence)
