"""Ask for the Modbus link, the bus address and the model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SerialPortSelector,
    TextSelector,
)
from modbus_connection import ModbusError
from mtdx62_modbus_library import Mtdx62Device

from .const import (
    CONF_BAUDRATE,
    CONF_MODEL,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_TYPE,
    CONF_UNIT_ID,
    DEFAULT_BAUDRATE,
    DEFAULT_PARITY,
    DEFAULT_PORT,
    DEFAULT_STOPBITS,
    DEFAULT_UNIT_ID,
    DOMAIN,
    MODEL_MTD062,
    MODELS,
    PARITY_OPTIONS,
    STOPBIT_OPTIONS,
    TYPE_SERIAL,
    TYPE_TCP,
)
from .helpers import create_modbus_params, create_title, create_unique_id


def _number(minimum: int, maximum: int) -> probatio.All[int]:
    """A boxed number field with hard bounds, handed back as an int."""
    return probatio.All(
        NumberSelector(NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=minimum, max=maximum)),
        probatio.Coerce(int),
    )


def _select(options: list[str]) -> SelectSelector:
    """A dropdown of the given options."""
    return SelectSelector(SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN))


def _model_selector() -> SelectSelector:
    """Let the user say which of the two models this is."""
    return SelectSelector(
        SelectSelectorConfig(
            options=list(MODELS),
            mode=SelectSelectorMode.DROPDOWN,
            translation_key=CONF_MODEL,
        )
    )


STEP_TCP_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): TextSelector(),
        probatio.Required(CONF_PORT, default=DEFAULT_PORT): _number(1, 65535),
        probatio.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): _number(1, 247),
        probatio.Required(CONF_MODEL, default=MODEL_MTD062): _model_selector(),
    }
)

STEP_SERIAL_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_DEVICE): SerialPortSelector(),
        probatio.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): _number(1200, 57600),
        probatio.Required(CONF_PARITY, default=DEFAULT_PARITY): _select(PARITY_OPTIONS),
        # Front ends send this field both as the option string and as a number, and
        # probatio validates defaults like any other value, so the string first.
        probatio.Required(CONF_STOPBITS, default=str(DEFAULT_STOPBITS)): probatio.All(
            probatio.Coerce(str),
            _select([str(stopbits) for stopbits in STOPBIT_OPTIONS]),
            probatio.Coerce(int),
        ),
        probatio.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): _number(1, 247),
        probatio.Required(CONF_MODEL, default=MODEL_MTD062): _model_selector(),
    }
)

SCHEMAS = {TYPE_TCP: STEP_TCP_SCHEMA, TYPE_SERIAL: STEP_SERIAL_SCHEMA}


async def _async_validate(hass: HomeAssistant, data: Mapping[str, Any]) -> None:
    """Read the sensor once, through a unit nobody holds yet."""
    async with async_get_temporary_unit(
        hass, create_modbus_params(data), data[CONF_UNIT_ID]
    ) as unit:
        await Mtdx62Device(unit).async_update_readings()


class Mtdx62ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Collect the link settings and one bus address per device."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Offer the two ways to reach a Modbus device."""
        return self.async_show_menu(step_id="user", menu_options=[TYPE_TCP, TYPE_SERIAL])

    async def async_step_tcp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Collect network settings."""
        return await self._async_step_connection(TYPE_TCP, user_input)

    async def async_step_serial(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Collect serial port settings."""
        return await self._async_step_connection(TYPE_SERIAL, user_input)

    async def _async_step_connection(
        self, connection_type: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Validate the link with a real read, then create the entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_TYPE: connection_type, **user_input}
            errors = await self._async_check(data)
            if not errors:
                await self.async_set_unique_id(create_unique_id(data))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=create_title(data), data=data)
        return self.async_show_form(
            step_id=connection_type,
            data_schema=SCHEMAS[connection_type],
            errors=errors,
        )

    async def _async_check(self, data: Mapping[str, Any]) -> dict[str, str]:
        """Report why the device could not be reached, if it could not."""
        try:
            await _async_validate(self.hass, data)
        except ModbusError:
            return {"base": "cannot_connect"}
        except HomeAssistantError:
            return {"base": "connection_conflict"}
        return {}

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the link settings, or the bus address, of an existing entry."""
        entry: ConfigEntry = self._get_reconfigure_entry()
        connection_type = entry.data[CONF_TYPE]
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_TYPE: connection_type, **user_input}
            errors = await self._async_check(data)
            if not errors:
                unique_id = create_unique_id(data)
                if self._another_entry_owns(unique_id, entry):
                    return self.async_abort(reason="already_configured")
                await self.async_set_unique_id(unique_id)
                return self.async_update_reload_and_abort(
                    entry, unique_id=unique_id, data=data, title=create_title(data)
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(SCHEMAS[connection_type], entry.data),
            errors=errors,
        )

    def _another_entry_owns(self, unique_id: str, entry: ConfigEntry) -> bool:
        """Whether a different entry already claims this sensor's identity.

        The helper for uniqueness aborts on the entry being reconfigured as well,
        which would refuse a form submitted without changes.
        """
        return any(
            other.unique_id == unique_id and other.entry_id != entry.entry_id
            for other in self._async_current_entries()
        )
