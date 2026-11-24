"""Diagnostics for a bug report: what the sensor says, with identifying data cut."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant
from modbus_connection import ModbusError

from . import Mtdx62ConfigEntry
from .const import (
    CONF_MODEL,
    CONF_UNIT_ID,
    MODELS,
    RAW_DIAGNOSTIC_NAMES,
    SETTINGS_DIAGNOSTIC_FIELDS,
)
from .coordinator import Mtdx62Coordinator

# The serial port path identifies the installation; the model name stays.
TO_REDACT = {CONF_DEVICE}


async def _async_collect(coordinator: Mtdx62Coordinator) -> dict[str, Any]:
    """Shape one entry's diagnostics, degrading when the sensor is silent."""
    device = coordinator.device
    entry = coordinator.config_entry
    readings = device.readings

    settings: dict[str, Any] | None = None
    settings_error: str | None = None
    try:
        await device.async_update_settings()
    except ModbusError as err:
        settings_error = type(err).__name__
    else:
        settings = {field: getattr(device.settings, field) for field in SETTINGS_DIAGNOSTIC_FIELDS}

    raw: dict[str, Any] | None = None
    raw_error: str | None = None
    try:
        raw = await device.async_read_raw(RAW_DIAGNOSTIC_NAMES)
    except ModbusError as err:
        raw_error = type(err).__name__

    status = readings.status
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "model": MODELS[entry.data[CONF_MODEL]],
        "unit_id": entry.data[CONF_UNIT_ID],
        "device": {
            "presence": readings.presence,
            "illuminance": readings.illuminance,
            "distance": readings.distance,
            "status_code": readings.status_code,
            "status": status.name if status is not None else None,
            "app_version": readings.app_version,
            "radar_version": readings.radar_version,
        },
        "settings": settings,
        "settings_error": settings_error,
        "raw_registers": raw,
        "raw_registers_error": raw_error,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: Mtdx62ConfigEntry
) -> dict[str, Any]:
    """Diagnostics for the whole entry."""
    return await _async_collect(entry.runtime_data)


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: Mtdx62ConfigEntry, device: object
) -> dict[str, Any]:
    """Diagnostics for the one device the entry owns."""
    return await _async_collect(entry.runtime_data)
