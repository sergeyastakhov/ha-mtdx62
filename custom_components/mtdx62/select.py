"""Select entities for the bus speed and parity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Mtdx62ConfigEntry
from .const import (
    BAUDRATE_OPTIONS,
    BUS_PARITY_CODE_BY_OPTION,
    BUS_PARITY_OPTION_BY_CODE,
    BUS_PARITY_OPTIONS,
    CONF_ALLOW_BUS_SETTINGS,
)
from .coordinator import Mtdx62Coordinator
from .entity import Mtdx62Entity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class Mtdx62SelectDescription(SelectEntityDescription):
    """A bus parameter whose meaningful values are a list, not a range."""

    field: str
    to_option: Callable[[Any], str | None]
    to_value: Callable[[str], int]


SELECTS: Final[tuple[Mtdx62SelectDescription, ...]] = (
    Mtdx62SelectDescription(
        key="baudrate",
        translation_key="baudrate",
        field="baudrate",
        options=list(BAUDRATE_OPTIONS),
        to_option=lambda value: None if value is None else str(value),
        to_value=int,
    ),
    Mtdx62SelectDescription(
        key="parity",
        translation_key="parity",
        field="parity",
        options=list(BUS_PARITY_OPTIONS),
        to_option=lambda value: (
            None if value is None else BUS_PARITY_OPTION_BY_CODE.get(int(value))
        ),
        to_value=lambda option: BUS_PARITY_CODE_BY_OPTION[option],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Mtdx62ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the bus selects only when the user allowed changing them."""
    if not entry.options.get(CONF_ALLOW_BUS_SETTINGS, False):
        return
    coordinator = entry.runtime_data
    known = {spec.name for spec in coordinator.device.settings.writable_fields()}
    async_add_entities(
        Mtdx62Select(coordinator, description)
        for description in SELECTS
        if description.field in known
    )


class Mtdx62Select(Mtdx62Entity, SelectEntity):
    """One bus parameter of the sensor."""

    entity_description: Mtdx62SelectDescription
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: Mtdx62Coordinator,
        description: Mtdx62SelectDescription,
    ) -> None:
        """Remember which parameter this entity writes."""
        super().__init__(coordinator, description.field)
        self.entity_description = description

    @property
    def current_option(self) -> str | None:
        """The value the sensor reports, as one of the options."""
        value = getattr(self.coordinator.device.settings, self.entity_description.field)
        return self.entity_description.to_option(value)

    async def async_select_option(self, option: str) -> None:
        """Write the option; the coordinator warns about the lost link."""
        await self.coordinator.async_write_bus_setting(
            self.entity_description.field, self.entity_description.to_value(option)
        )
