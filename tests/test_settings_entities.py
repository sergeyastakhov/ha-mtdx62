"""The settings entities: hidden by default, writable once enabled."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from modbus_connection import IllegalDataValueError, ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit, WriteEvent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtdx62.const import DOMAIN, ISSUE_BUS_SETTINGS_CHANGED

SETTINGS = (
    "detection_distance",
    "shielding_distance",
    "entry_indent",
    "entry_delay",
    "departure_delay",
    "trigger_sensitivity",
    "maintain_sensitivity",
    "light_threshold",
)


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str) -> str | None:
    """Find an entity by its unique id."""
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")


def recorder(unit: MockModbusUnit) -> list[WriteEvent]:
    """Every write the integration sent."""
    seen: list[WriteEvent] = []
    unit.on_write(seen.append)
    return seen


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry and let the platforms settle."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def enable(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str) -> str:
    """Turn on an entity that ships disabled and return its id."""
    found = entity_id(hass, entry, domain, key)
    assert found is not None
    er.async_get(hass).async_update_entity(found, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    return found


async def test_settings_are_hidden_by_default(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """Eight numbers are registered, all disabled, so the block stays quiet."""
    await setup(hass, mock_entry)

    for field in SETTINGS:
        found = entity_id(hass, mock_entry, "number", field)
        assert found is not None, field
        entry = er.async_get(hass).async_get(found)
        assert entry is not None
        assert entry.disabled_by is not None, field
        assert hass.states.get(found) is None, field


async def test_no_bus_entities(hass: HomeAssistant, mock_entry: MockConfigEntry) -> None:
    """The bus address, speed and parity are not entities at all."""
    await setup(hass, mock_entry)

    for field in ("unit_id", "baudrate", "parity"):
        assert entity_id(hass, mock_entry, "number", field) is None, field
        assert entity_id(hass, mock_entry, "select", field) is None, field


async def test_an_enabled_setting_can_be_written(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """Enabling the entity is the permission to change the value."""
    await setup(hass, mock_entry)
    found = await enable(hass, mock_entry, "number", "detection_distance")

    await hass.services.async_call(
        "number", "set_value", {"entity_id": found, "value": 4.5}, blocking=True
    )
    await hass.async_block_till_done()

    assert patched_unit.holding[0] == 450
    state = hass.states.get(found)
    assert state is not None
    assert float(state.state) == 4.5


async def test_limits_come_from_the_library(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """The entity shows the library's range, not a copy of it."""
    await setup(hass, mock_entry)
    found = await enable(hass, mock_entry, "number", "detection_distance")
    state = hass.states.get(found)
    assert state is not None
    assert float(state.attributes["min"]) == 1.0
    assert float(state.attributes["max"]) == 10.0
    assert float(state.attributes["step"]) == 0.01
    assert state.attributes["unit_of_measurement"] == "m"


async def test_a_booting_sensor_is_not_written(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """While the sensor reports its self-check, settings are refused."""
    patched_unit.input[0] = [0, 0, 0, 0, 0x0001, 0x0103, 0, 0]
    await setup(hass, mock_entry)
    found = await enable(hass, mock_entry, "number", "detection_distance")
    seen = recorder(patched_unit)

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": found, "value": 4.5}, blocking=True
        )

    assert caught.value.translation_key == "device_not_ready"
    assert seen == []


async def test_zones_must_fit_into_the_range(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The sensor's own rule is checked before the write, with a clear message."""
    patched_unit.holding[0] = 400
    patched_unit.holding[1] = 300
    patched_unit.holding[6] = 60
    await setup(hass, mock_entry)
    found = await enable(hass, mock_entry, "number", "entry_indent")

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": found, "value": 1.5}, blocking=True
        )

    assert caught.value.translation_key == "zones_do_not_fit"
    assert patched_unit.holding[6] == 60


async def test_a_clamped_value_is_reported(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """If the sensor keeps another number, the user hears about it."""
    patched_unit.on_write(lambda event: patched_unit.holding.__setitem__(event.address, 7))
    await setup(hass, mock_entry)
    found = await enable(hass, mock_entry, "number", "trigger_sensitivity")

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": found, "value": 9}, blocking=True
        )

    assert caught.value.translation_key == "value_not_stored"


async def test_a_rejected_value_is_reported(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """An exception from the sensor is not the same as a value that did not stick."""
    patched_unit.fail_write(4, IllegalDataValueError("no such value"))
    await setup(hass, mock_entry)
    found = await enable(hass, mock_entry, "number", "trigger_sensitivity")

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": found, "value": 9}, blocking=True
        )

    assert caught.value.translation_key == "device_rejected"


async def test_a_silent_sensor_is_reported(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """A timeout reads as "no answer", not as a refused value."""
    patched_unit.fail_write(4, ModbusTimeoutError("no answer"))
    await setup(hass, mock_entry)
    found = await enable(hass, mock_entry, "number", "trigger_sensitivity")

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": found, "value": 9}, blocking=True
        )

    assert caught.value.translation_key == "no_answer"


async def test_the_mac_sensor_is_diagnostic_and_disabled(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The MAC code is there for a bug report, not for the everyday view."""
    patched_unit.holding[13] = 1
    await setup(hass, mock_entry)
    found = entity_id(hass, mock_entry, "sensor", "mac_code")
    assert found is not None
    entry = er.async_get(hass).async_get(found)
    assert entry is not None
    assert entry.disabled_by is not None
    assert entry.entity_category == "diagnostic"

    found = await enable(hass, mock_entry, "sensor", "mac_code")
    state = hass.states.get(found)
    assert state is not None
    assert state.state == "1"


async def test_the_zone_check_waits_for_real_values(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """Before the first settings read the rule is meaningless, not violated."""
    await setup(hass, mock_entry)
    coordinator = mock_entry.runtime_data

    with patch.object(
        type(coordinator.device.settings),
        "detection_distance",
        property(lambda self: None),
    ):
        coordinator._require_zones_fit("entry_indent", 1.5)

    with patch.object(
        type(coordinator.device.settings),
        "detection_distance",
        property(lambda self: 0.0),
    ):
        coordinator._require_zones_fit("entry_indent", 1.5)


async def test_a_failed_settings_read_keeps_the_poll(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The measurements came through; a failed parameter read must not hide them."""
    patched_unit.fail_read(0, ModbusTimeoutError("no answer"))
    await setup(hass, mock_entry)

    presence = hass.states.get(entity_id(hass, mock_entry, "binary_sensor", "presence") or "")
    assert presence is not None
    assert presence.state == "on"


async def test_a_fault_clearing_is_logged(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The fault is reported once, and its departure once as well."""
    patched_unit.input[0] = [1, 42, 250, 4, 0x0001, 0x0103, 0, 0]
    await setup(hass, mock_entry)

    patched_unit.input[0] = [1, 42, 250, 1, 0x0001, 0x0103, 0, 0]
    await mock_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert mock_entry.runtime_data._reported_fault is None


async def test_the_bus_write_creates_a_repair(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The dialog path: one batch write, a repair, and the entry left alone."""
    await setup(hass, mock_entry)
    coordinator = mock_entry.runtime_data
    seen: list[WriteEvent] = []
    patched_unit.on_write(seen.append)

    await coordinator.async_write_link_settings(unit_id=5, baudrate=19200, parity=2)
    await hass.async_block_till_done()

    assert len(seen) == 1
    assert seen[0].function_code == 0x10
    assert seen[0].values == [5, 19200, 2]
    assert mock_entry.data["unit_id"] == 1
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_BUS_SETTINGS_CHANGED) is not None


async def test_the_coordinator_refuses_a_value_the_library_rejects(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The entity form constrains input; the coordinator still guards the library."""
    await setup(hass, mock_entry)
    coordinator = mock_entry.runtime_data

    with pytest.raises(HomeAssistantError) as caught:
        await coordinator.async_write_setting("departure_delay", 1)

    assert caught.value.translation_key == "value_out_of_range"


async def test_a_bus_value_out_of_range_never_reaches_the_bus(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The batch is validated before the request."""
    await setup(hass, mock_entry)
    seen: list[WriteEvent] = []
    patched_unit.on_write(seen.append)

    with pytest.raises(HomeAssistantError) as caught:
        await mock_entry.runtime_data.async_write_link_settings(
            unit_id=999, baudrate=9600, parity=0
        )

    assert caught.value.translation_key == "value_out_of_range"
    assert seen == []


async def test_a_silent_sensor_during_the_bus_write_is_reported(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """A timeout on the batch write is "no answer", not a refused value."""
    await setup(hass, mock_entry)
    patched_unit.fail_write(7, ModbusTimeoutError("no answer"))

    with pytest.raises(HomeAssistantError) as caught:
        await mock_entry.runtime_data.async_write_link_settings(unit_id=5, baudrate=19200, parity=2)

    assert caught.value.translation_key == "no_answer"


async def test_the_repair_goes_away_when_the_sensor_answers(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """After the user reconfigured the entry, a poll clears the stale repair."""
    await setup(hass, mock_entry)
    await mock_entry.runtime_data.async_write_link_settings(unit_id=5, baudrate=19200, parity=2)
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_BUS_SETTINGS_CHANGED) is not None

    await mock_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_BUS_SETTINGS_CHANGED) is None
