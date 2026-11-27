"""The bus-settings dialog: warning, confirmation, one request."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit, WriteEvent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtdx62.const import (
    CONF_BAUDRATE,
    CONF_CONFIRM,
    CONF_PARITY,
    CONF_UNIT_ID,
    DOMAIN,
    ISSUE_BUS_SETTINGS_CHANGED,
)


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add the entry and let the platforms settle."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def start(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Open the options dialog."""
    return await hass.config_entries.options.async_init(entry.entry_id)


async def test_the_dialog_shows_the_current_values(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """The form is prefilled from the sensor, not from defaults."""
    await setup(hass, mock_entry)

    result = await start(hass, mock_entry)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    fields = {marker.schema for marker in result["data_schema"].schema}
    assert {CONF_UNIT_ID, CONF_BAUDRATE, CONF_PARITY} <= fields


async def test_unchanged_values_write_nothing(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """Opening the dialog and closing it must not touch the sensor."""
    await setup(hass, mock_entry)
    seen: list[WriteEvent] = []
    patched_unit.on_write(seen.append)

    result = await start(hass, mock_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_UNIT_ID: 1, CONF_BAUDRATE: "9600", CONF_PARITY: "none"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert seen == []
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_BUS_SETTINGS_CHANGED) is None


async def test_changed_values_need_confirmation(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The three values are written only after the warning is accepted."""
    await setup(hass, mock_entry)
    seen: list[WriteEvent] = []
    patched_unit.on_write(seen.append)

    result = await start(hass, mock_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_UNIT_ID: 5, CONF_BAUDRATE: "19200", CONF_PARITY: "even"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bus_settings_confirm"
    assert seen == []

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONFIRM: True}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(seen) == 1
    assert seen[0].function_code == 0x10
    assert seen[0].values == [5, 19200, 2]
    assert mock_entry.data[CONF_UNIT_ID] == 1
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_BUS_SETTINGS_CHANGED) is not None


async def test_declining_writes_nothing(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """Changing your mind at the warning keeps the sensor as it was."""
    await setup(hass, mock_entry)
    seen: list[WriteEvent] = []
    patched_unit.on_write(seen.append)

    result = await start(hass, mock_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_UNIT_ID: 5, CONF_BAUDRATE: "19200", CONF_PARITY: "even"},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONFIRM: False}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert seen == []
    assert patched_unit.holding[7] == 1


async def test_a_refused_write_is_reported_in_the_dialog(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """A dead link in the middle of the dialog keeps the user where they were."""
    await setup(hass, mock_entry)
    patched_unit.fail_write(7, ModbusTimeoutError("no answer"))

    result = await start(hass, mock_entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_UNIT_ID: 5, CONF_BAUDRATE: "19200", CONF_PARITY: "even"},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONFIRM: True}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bus_settings_confirm"
    assert result["errors"] == {"base": "cannot_write"}
    assert mock_entry.data[CONF_UNIT_ID] == 1


async def test_the_entry_reloads_after_the_dialog(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """Saving the dialog makes the entry pick up its new state."""
    await setup(hass, mock_entry)

    result = await start(hass, mock_entry)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_UNIT_ID: 1, CONF_BAUDRATE: "9600", CONF_PARITY: "none"},
    )
    await hass.async_block_till_done()

    assert mock_entry.state is ConfigEntryState.LOADED
