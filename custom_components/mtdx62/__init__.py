"""Integrate MTD062-MB and MTD262-MB presence sensors over Modbus."""

from __future__ import annotations

from homeassistant.components.modbus import async_get_unit
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from mtdx62_modbus_library import Mtdx62Device

from .const import CONF_UNIT_ID
from .coordinator import Mtdx62Coordinator
from .helpers import create_modbus_params

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]

type Mtdx62ConfigEntry = ConfigEntry[Mtdx62Coordinator]


async def async_setup_entry(hass: HomeAssistant, entry: Mtdx62ConfigEntry) -> bool:
    """Set up one sensor from a config entry.

    The connection belongs to the ``modbus`` integration: this integration asks
    for this unit and never opens a link of its own.
    """
    unit = async_get_unit(
        hass,
        entry,
        create_modbus_params(entry.data),
        entry.data[CONF_UNIT_ID],
    )
    device = Mtdx62Device(unit)
    coordinator = Mtdx62Coordinator(hass, entry, device)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: Mtdx62ConfigEntry) -> None:
    """Reload after the options changed: the bus entities come and go with it."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: Mtdx62ConfigEntry) -> bool:
    """Unload the platforms. The shared connection is not ours to close."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    entry.runtime_data.async_clear_repairs()
    return True
