"""The settings entities: what exists, its limits, and how writes land."""

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

from custom_components.mtdx62.const import (
    CONF_ALLOW_BUS_SETTINGS,
    DOMAIN,
    ISSUE_BUS_SETTINGS_CHANGED,
)

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


def entry_with(entry_data: dict[str, object], **options: object) -> MockConfigEntry:
    """A config entry with the given options, which cannot be set afterwards."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="MTD062-MB (5.8 GHz)",
        data=entry_data,
        options=dict(options),
        unique_id="tcp:192.168.1.50:502#1",
    )


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


async def test_eight_settings_and_no_bus_entities(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """By default the user gets the ordinary parameters, nothing that can cut the link."""
    await setup(hass, mock_entry)

    for field in SETTINGS:
        assert entity_id(hass, mock_entry, "number", field) is not None, field
    for field in ("unit_id", "baudrate", "parity"):
        assert entity_id(hass, mock_entry, "number", field) is None, field
        assert entity_id(hass, mock_entry, "select", field) is None, field


async def test_limits_come_from_the_library(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """The entity shows the library's range, not a copy of it."""
    await setup(hass, mock_entry)
    found = entity_id(hass, mock_entry, "number", "detection_distance")
    assert found is not None
    state = hass.states.get(found)
    assert state is not None
    assert float(state.attributes["min"]) == 1.0
    assert float(state.attributes["max"]) == 10.0
    assert float(state.attributes["step"]) == 0.01
    assert state.attributes["unit_of_measurement"] == "m"


async def test_a_setting_is_written_and_confirmed(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """Setting a number reaches the register and the entity shows the stored value."""
    await setup(hass, mock_entry)
    found = entity_id(hass, mock_entry, "number", "detection_distance")
    assert found is not None

    await hass.services.async_call(
        "number", "set_value", {"entity_id": found, "value": 4.5}, blocking=True
    )
    await hass.async_block_till_done()

    assert patched_unit.holding[0] == 450
    state = hass.states.get(found)
    assert state is not None
    assert float(state.state) == 4.5


async def test_a_booting_sensor_is_not_written(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """While the sensor reports its self-check, settings are refused."""
    patched_unit.input[0] = [0, 0, 0, 0, 0x0001, 0x0103, 0, 0]
    await setup(hass, mock_entry)
    seen = recorder(patched_unit)
    found = entity_id(hass, mock_entry, "number", "detection_distance")
    assert found is not None

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
    found = entity_id(hass, mock_entry, "number", "entry_indent")
    assert found is not None

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
    found = entity_id(hass, mock_entry, "number", "trigger_sensitivity")
    assert found is not None

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": found, "value": 9}, blocking=True
        )

    assert caught.value.translation_key == "value_not_stored"


async def test_bus_entities_appear_only_with_the_option(
    hass: HomeAssistant, entry_data: dict[str, object]
) -> None:
    """The address, speed and parity are behind the switch the user turns on."""
    mock_entry = entry_with(entry_data, **{CONF_ALLOW_BUS_SETTINGS: True})
    await setup(hass, mock_entry)

    assert entity_id(hass, mock_entry, "number", "unit_id") is not None
    baudrate = entity_id(hass, mock_entry, "select", "baudrate")
    assert baudrate is not None
    state = hass.states.get(baudrate)
    assert state is not None
    assert state.state == "9600"


async def test_writing_the_address_creates_a_repair(
    hass: HomeAssistant, entry_data: dict[str, object], patched_unit: MockModbusUnit
) -> None:
    """The value lands in the sensor, the entry keeps its link, a repair says so."""
    mock_entry = entry_with(entry_data, **{CONF_ALLOW_BUS_SETTINGS: True})
    await setup(hass, mock_entry)
    found = entity_id(hass, mock_entry, "number", "unit_id")
    assert found is not None

    await hass.services.async_call(
        "number", "set_value", {"entity_id": found, "value": 5}, blocking=True
    )
    await hass.async_block_till_done()

    assert patched_unit.holding[7] == 5
    assert mock_entry.data["unit_id"] == 1
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_BUS_SETTINGS_CHANGED)
    assert issue is not None


async def test_the_parity_select_maps_to_the_register(
    hass: HomeAssistant, entry_data: dict[str, object], patched_unit: MockModbusUnit
) -> None:
    """The option names are translated; the register gets the code."""
    mock_entry = entry_with(entry_data, **{CONF_ALLOW_BUS_SETTINGS: True})
    await setup(hass, mock_entry)
    found = entity_id(hass, mock_entry, "select", "parity")
    assert found is not None

    await hass.services.async_call(
        "select", "select_option", {"entity_id": found, "option": "even"}, blocking=True
    )
    await hass.async_block_till_done()

    assert patched_unit.holding[9] == 2


async def test_a_rejected_value_is_reported(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """An exception from the sensor is not the same as a value that did not stick."""
    patched_unit.fail_write(4, IllegalDataValueError("no such value"))
    await setup(hass, mock_entry)
    found = entity_id(hass, mock_entry, "number", "trigger_sensitivity")
    assert found is not None

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
    found = entity_id(hass, mock_entry, "number", "trigger_sensitivity")
    assert found is not None

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": found, "value": 9}, blocking=True
        )

    assert caught.value.translation_key == "no_answer"


async def test_a_bus_value_out_of_range_is_refused(
    hass: HomeAssistant, entry_data: dict[str, object], patched_unit: MockModbusUnit
) -> None:
    """The library's range check is translated into a form error."""
    entry = entry_with(entry_data, **{CONF_ALLOW_BUS_SETTINGS: True})
    await setup(hass, entry)
    coordinator = entry.runtime_data

    with pytest.raises(HomeAssistantError) as caught:
        await coordinator.async_write_bus_setting("unit_id", 999)

    assert caught.value.translation_key == "value_out_of_range"


async def test_a_bus_write_without_an_answer_is_reported(
    hass: HomeAssistant, entry_data: dict[str, object], patched_unit: MockModbusUnit
) -> None:
    """A silent sensor on a bus write gets its own message."""
    entry = entry_with(entry_data, **{CONF_ALLOW_BUS_SETTINGS: True})
    await setup(hass, entry)
    patched_unit.fail_write(7, ModbusTimeoutError("no answer"))

    with pytest.raises(HomeAssistantError) as caught:
        await entry.runtime_data.async_write_bus_setting("unit_id", 5)

    assert caught.value.translation_key == "no_answer"


async def test_the_repair_goes_away_when_the_sensor_answers(
    hass: HomeAssistant, entry_data: dict[str, object], patched_unit: MockModbusUnit
) -> None:
    """After the user reconfigured the entry, a poll clears the stale repair."""
    entry = entry_with(entry_data, **{CONF_ALLOW_BUS_SETTINGS: True})
    await setup(hass, entry)
    await entry.runtime_data.async_write_bus_setting("unit_id", 5)
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_BUS_SETTINGS_CHANGED) is not None

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_BUS_SETTINGS_CHANGED) is None


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


async def test_the_coordinator_refuses_a_value_the_library_rejects(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The entity form constrains input; the coordinator still guards the library."""
    await setup(hass, mock_entry)
    coordinator = mock_entry.runtime_data

    with pytest.raises(HomeAssistantError) as caught:
        await coordinator.async_write_setting("departure_delay", 1)

    assert caught.value.translation_key == "value_out_of_range"


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
