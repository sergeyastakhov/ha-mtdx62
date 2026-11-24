"""A self-check that never finishes raises a repair the user can act on."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtdx62.const import (
    DOMAIN,
    ISSUE_SELF_CHECK_STUCK,
    SELF_CHECK_STUCK_AFTER,
)


def self_check_repairs(hass: HomeAssistant) -> list[ir.IssueEntry]:
    """Every self-check repair the registry holds for this domain."""
    return [
        item
        for item in ir.async_get(hass).issues.values()
        if item.domain == DOMAIN and item.issue_id == ISSUE_SELF_CHECK_STUCK
    ]


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Run one more poll, as the coordinator would on its interval."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_stuck_self_check_raises_one_repair(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    patched_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A sensor that never leaves code 0 is not booting, and only the user can help."""
    patched_unit.input[3] = 0
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert self_check_repairs(hass) == []

    freezer.tick(SELF_CHECK_STUCK_AFTER + timedelta(seconds=5))
    await refresh(hass, mock_entry)
    assert len(self_check_repairs(hass)) == 1

    freezer.tick(timedelta(minutes=5))
    await refresh(hass, mock_entry)
    assert len(self_check_repairs(hass)) == 1


async def test_short_self_check_raises_nothing(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    patched_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A normal power-up finishes in seconds and must stay quiet."""
    patched_unit.input[3] = 0
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(timedelta(seconds=5))
    await refresh(hass, mock_entry)
    patched_unit.input[3] = 1
    await refresh(hass, mock_entry)

    assert self_check_repairs(hass) == []


async def test_repair_clears_when_the_sensor_moves_on(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    patched_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Whatever replaces the self-check explains itself elsewhere, so the repair goes."""
    patched_unit.input[3] = 0
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    freezer.tick(SELF_CHECK_STUCK_AFTER + timedelta(seconds=5))
    await refresh(hass, mock_entry)
    assert len(self_check_repairs(hass)) == 1

    patched_unit.input[3] = 4
    await refresh(hass, mock_entry)

    assert self_check_repairs(hass) == []
