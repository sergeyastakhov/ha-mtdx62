"""Diagnostics carry what helps and drop what identifies the installation."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtdx62.const import CONF_UNIT_ID, TYPE_SERIAL
from custom_components.mtdx62.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)


async def test_diagnostics_report_the_device(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """Measurements, parameters, versions and raw registers reach the file."""
    patched_unit.holding[0] = [600, 60, 10, 30, 7, 7, 60, 1, 9600, 1, 2, 1000, 600]
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_entry)

    assert diagnostics["model"] == "MTD062-MB (5.8 GHz)"
    assert diagnostics["unit_id"] == 1
    assert diagnostics["device"]["presence"] is True
    assert diagnostics["device"]["illuminance"] == 42
    assert diagnostics["device"]["app_version"] == "1.2.3"
    assert diagnostics["settings"]["detection_distance"] == 6.0
    assert diagnostics["settings_error"] is None
    assert diagnostics["raw_registers"]["input"][0] == 1


async def test_diagnostics_redact_the_serial_port(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """The port path says where the installation is, so it is cut."""
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    hass.config_entries.async_update_entry(
        mock_entry,
        data={
            "type": TYPE_SERIAL,
            "device": "/dev/serial/by-id/usb-FTDI-if00-port0",
            "baudrate": 9600,
            "parity": "O",
            "stopbits": 1,
            CONF_UNIT_ID: 1,
            "model": "mtd062-mb",
        },
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_entry)

    assert diagnostics["entry"]["device"] == "**REDACTED**"
    assert diagnostics["entry"]["type"] == TYPE_SERIAL
    assert "/dev/serial/by-id" not in str(diagnostics)


async def test_diagnostics_keep_values_while_entities_hide_them(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """An untrusted measurement is hidden in the UI but still useful in the dump."""
    patched_unit.input[3] = 4
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_entry)

    assert diagnostics["device"]["presence"] is True
    assert diagnostics["device"]["illuminance"] == 42
    assert diagnostics["device"]["status_code"] == 4
    assert diagnostics["device"]["status"] == "RADAR_FAULT"
    assert diagnostics["raw_registers"]["input"][0] == 1


async def test_diagnostics_survive_a_silent_sensor(
    hass: HomeAssistant, mock_entry: MockConfigEntry, patched_unit: MockModbusUnit
) -> None:
    """A user can still download diagnostics while the sensor is off."""
    mock_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    patched_unit.fail_requests(ModbusTimeoutError())
    diagnostics = await async_get_device_diagnostics(hass, mock_entry, object())

    assert diagnostics["settings"] is None
    assert diagnostics["settings_error"] == "ModbusTimeoutError"
    assert diagnostics["raw_registers"] is None
    assert diagnostics["entry"] is not None
