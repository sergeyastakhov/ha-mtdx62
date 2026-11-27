"""Ask for the Modbus link, the bus address and the model."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SerialPortSelector,
    TextSelector,
)
from modbus_connection import ModbusConnectionError, ModbusError
from mtdx62_modbus_library import Mtdx62Device
from probatio import Schema

from .const import (
    BAUDRATE_OPTIONS,
    BUS_PARITY_CODE_BY_OPTION,
    BUS_PARITY_OPTION_BY_CODE,
    BUS_PARITY_OPTIONS,
    CONF_BAUDRATE,
    CONF_CONFIRM,
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
from .helpers import (
    create_link_label,
    create_modbus_params,
    create_title,
    create_unique_id,
    held_serial_links,
    present_serial_ports,
    same_device_under_another_path,
    serial_port_exists,
    yaml_hub_for,
    yaml_hubs_using,
)

_LOGGER = logging.getLogger(__name__)


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

BUS_SETTINGS_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): _number(1, 247),
        probatio.Required(CONF_BAUDRATE, default=str(DEFAULT_BAUDRATE)): _select(
            list(BAUDRATE_OPTIONS)
        ),
        probatio.Required(CONF_PARITY, default="none"): _select(list(BUS_PARITY_OPTIONS)),
    }
)

CONFIRM_SCHEMA = probatio.Schema(
    {probatio.Required(CONF_CONFIRM, default=False): BooleanSelector()}
)


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
        placeholders: dict[str, str] = {}
        data: dict[str, Any] | None = None
        if user_input is not None:
            data = {CONF_TYPE: connection_type, **user_input}
            errors, placeholders = await self._async_check(data)
            if not errors:
                await self.async_set_unique_id(create_unique_id(data))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=create_title(data), data=data)
        return self.async_show_form(
            step_id=connection_type,
            data_schema=self._form(connection_type, user_input),
            errors=errors,
            description_placeholders=placeholders or None,
        )

    def _form(self, connection_type: str, user_input: dict[str, Any] | None) -> Schema:
        """The form, prefilled with what the user just typed when a check failed.

        Without this the browser falls back to the defaults and the user has to
        retype the port and the address after every failed attempt.
        """
        schema = SCHEMAS[connection_type]
        if user_input is None:
            return schema
        return self.add_suggested_values_to_schema(schema, user_input)

    async def _async_check(self, data: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
        """Report why the device could not be reached, if it could not."""
        placeholders = {"link": create_link_label(data)}
        try:
            await _async_validate(self.hass, data)
        except ModbusConnectionError as err:
            _LOGGER.debug("cannot open the link %s: %s", create_unique_id(data), err)
            _LOGGER.debug(
                "serial links the modbus component holds: %s",
                ", ".join(held_serial_links(self.hass)) or "none",
            )
            _LOGGER.debug(
                "serial ports used by a YAML modbus setup: %s",
                ", ".join(f"{port} ({name})" for name, port in yaml_hubs_using(self.hass))
                or "none",
            )
            hub = yaml_hub_for(self.hass, data)
            if hub is not None:
                return {"base": "port_used_by_yaml_hub"}, {**placeholders, "hub": hub}
            held = same_device_under_another_path(self.hass, data)
            if held is not None:
                _LOGGER.debug("the same device is already open as %s", held)
                return {"base": "port_held_elsewhere"}, {**placeholders, "held": held}
            if not serial_port_exists(data):
                _LOGGER.debug(
                    "serial ports present: %s", ", ".join(present_serial_ports()) or "none"
                )
                return {"base": "port_missing"}, placeholders
            return {"base": "cannot_open_link"}, placeholders
        except ModbusError as err:
            _LOGGER.debug("no answer from %s: %s", create_unique_id(data), err)
            return {"base": "cannot_connect"}, placeholders
        except HomeAssistantError as err:
            _LOGGER.debug("the link %s is taken: %s", create_unique_id(data), err)
            return {"base": "connection_conflict"}, placeholders
        return {}, placeholders

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> Mtdx62OptionsFlow:
        """Offer the switch that unlocks the bus settings."""
        return Mtdx62OptionsFlow()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the link settings, or the bus address, of an existing entry."""
        entry: ConfigEntry = self._get_reconfigure_entry()
        connection_type = entry.data[CONF_TYPE]
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_TYPE: connection_type, **user_input}
            errors, placeholders = await self._async_check(data)
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
            data_schema=self.add_suggested_values_to_schema(
                SCHEMAS[connection_type],
                user_input if user_input is not None else entry.data,
            ),
            errors=errors,
            description_placeholders=placeholders or None,
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


class Mtdx62OptionsFlow(OptionsFlow):
    """Change the sensor's bus settings, where a warning can be shown."""

    def __init__(self) -> None:
        """Start with nothing to write."""
        super().__init__()
        self._new_values: dict[str, int] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the three values that decide how the sensor answers."""
        entry: ConfigEntry = self.config_entry
        settings = entry.runtime_data.device.settings
        current_parity = (
            None if settings.parity is None else BUS_PARITY_OPTION_BY_CODE.get(settings.parity)
        )
        if user_input is not None:
            new_values = {
                CONF_UNIT_ID: int(user_input[CONF_UNIT_ID]),
                CONF_BAUDRATE: int(user_input[CONF_BAUDRATE]),
                CONF_PARITY: BUS_PARITY_CODE_BY_OPTION[user_input[CONF_PARITY]],
            }
            unchanged = (
                new_values[CONF_UNIT_ID] == settings.unit_id
                and new_values[CONF_BAUDRATE] == settings.baudrate
                and new_values[CONF_PARITY] == settings.parity
            )
            if unchanged:
                return self.async_create_entry(data={})
            self._new_values = new_values
            return await self.async_step_bus_settings_confirm()
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                BUS_SETTINGS_SCHEMA,
                {
                    CONF_UNIT_ID: settings.unit_id or DEFAULT_UNIT_ID,
                    CONF_BAUDRATE: str(settings.baudrate or DEFAULT_BAUDRATE),
                    CONF_PARITY: current_parity or "none",
                },
            ),
        )

    async def async_step_bus_settings_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """A form is not enough for an action that makes the sensor unreachable."""
        if user_input is not None:
            if not user_input.get(CONF_CONFIRM):
                return self.async_create_entry(data={})
            coordinator = self.config_entry.runtime_data
            try:
                await coordinator.async_write_link_settings(**self._new_values)
            except HomeAssistantError:
                return self.async_show_form(
                    step_id="bus_settings_confirm",
                    data_schema=CONFIRM_SCHEMA,
                    errors={"base": "cannot_write"},
                )
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="bus_settings_confirm", data_schema=CONFIRM_SCHEMA)
