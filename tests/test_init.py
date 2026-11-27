"""Setup, entities and the unavailable threshold."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtdx62.const import DOMAIN, MAX_CONSECUTIVE_FAILURES


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str) -> str:
    """Look an entity up by its unique id, independent of the device name."""
    registry = er.async_get(hass)
    found = registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    assert found is not None
    return found


def enable_entity(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str) -> str:
    """Turn on an entity that ships disabled, and return its id."""
    found = entity_id(hass, entry, domain, key)
    er.async_get(hass).async_update_entity(found, disabled_by=None)
    return found


async def test_setup_creates_the_entities(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """One entry yields presence, illuminance, distance and three diagnostics."""
    mock_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_entry.state is ConfigEntryState.LOADED
    presence = hass.states.get(entity_id(hass, mock_entry, "binary_sensor", "presence"))
    assert presence is not None
    assert presence.state == STATE_ON

    illuminance = hass.states.get(entity_id(hass, mock_entry, "sensor", "illuminance"))
    assert illuminance is not None
    assert illuminance.state == "4.2"


async def test_distance_is_disabled_by_default(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """Distance is off until someone needs it for tuning the detection zone."""
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    found = registry.async_get_entity_id("sensor", DOMAIN, f"{mock_entry.entry_id}_distance")
    assert found is not None
    assert registry.async_get(found).disabled_by is not None

    state = hass.states.get(found)
    assert state is None or state.state in (STATE_UNAVAILABLE, "unknown")


async def test_distance_shows_metres_with_two_decimals(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The value reaches the state machine in metres, with the sensor's resolution."""
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    found = registry.async_get_entity_id("sensor", DOMAIN, f"{mock_entry.entry_id}_distance")
    assert found is not None
    registry.async_update_entity(found, disabled_by=None)
    await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(found)
    assert state is not None
    assert state.state == "2.5"
    assert state.attributes["unit_of_measurement"] == "m"


async def test_three_failed_polls_make_it_unavailable(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """A single lost frame is tolerated; a run of them is an outage."""
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    presence_id = entity_id(hass, mock_entry, "binary_sensor", "presence")
    assert hass.states.get(presence_id).state == STATE_ON

    patched_unit.fail_requests(ModbusTimeoutError())
    coordinator = mock_entry.runtime_data
    for _ in range(MAX_CONSECUTIVE_FAILURES - 1):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get(presence_id).state == STATE_ON

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(presence_id).state == STATE_UNAVAILABLE

    patched_unit.fail_requests(None)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(presence_id).state == STATE_ON


async def test_unload_drops_the_entities(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """Unloading stops the polling and removes the entities."""
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_entry.state is ConfigEntryState.NOT_LOADED
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("binary_sensor", DOMAIN, f"{mock_entry.entry_id}_presence")
        is not None
    )


async def test_silent_sensor_at_startup_retries_later(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """A sensor that is off when Home Assistant starts is retried, not dropped."""
    patched_unit.fail_requests(ModbusTimeoutError())
    mock_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize(
    ("status_code", "label"),
    [
        pytest.param(0, "self-check", id="self-check"),
        pytest.param(2, "self-test-failed", id="self-test-failed"),
        pytest.param(4, "radar-fault", id="radar-fault"),
    ],
)
async def test_measurements_are_hidden_without_a_passed_self_test(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    patched_unit: MockModbusUnit,
    status_code: int,
    label: str,
) -> None:
    """Readings count only while the sensor reports that it is running."""
    patched_unit.input[3] = status_code
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    for domain, key in (("binary_sensor", "presence"), ("sensor", "illuminance")):
        state = hass.states.get(entity_id(hass, mock_entry, domain, key))
        assert state is not None
        assert state.state == STATE_UNAVAILABLE, f"{key} shows a value while {label}"

    status_id = enable_entity(hass, mock_entry, "sensor", "status")
    await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()
    status = hass.states.get(status_id)
    assert status is not None
    assert status.state != STATE_UNAVAILABLE


async def test_measurements_return_once_the_self_test_passes(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """A sensor that finishes its self-check becomes visible again."""
    patched_unit.input[3] = 0
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    presence_id = entity_id(hass, mock_entry, "binary_sensor", "presence")
    assert hass.states.get(presence_id).state == STATE_UNAVAILABLE

    patched_unit.input[3] = 1
    await mock_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(presence_id).state == STATE_ON


async def test_a_failed_unload_keeps_the_entry(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """When a platform refuses to unload, the entry stays loaded."""
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=False),
    ):
        assert not await hass.config_entries.async_unload(mock_entry.entry_id)

    assert mock_entry.state is ConfigEntryState.FAILED_UNLOAD
