"""The master: transport choice, validation, uniqueness and reconfiguration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from modbus_connection import ModbusTimeoutError
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtdx62.config_flow import _async_validate
from custom_components.mtdx62.const import (
    CONF_BAUDRATE,
    CONF_MODEL,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_TYPE,
    CONF_UNIT_ID,
    DEFAULT_BAUDRATE,
    DOMAIN,
    MODEL_MTD262,
    TYPE_SERIAL,
    TYPE_TCP,
)

VALIDATE = "custom_components.mtdx62.config_flow._async_validate"


@pytest.fixture
def validating() -> Generator[AsyncMock]:
    """Pretend the sensor answered, without touching a bus."""
    with patch(VALIDATE, new_callable=AsyncMock) as validate:
        yield validate


async def test_menu_offers_both_transports(hass: HomeAssistant) -> None:
    """The first step asks how the sensor is reached."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "user"
    assert result["menu_options"] == ["tcp", "serial"]


async def test_tcp_entry_is_created(
    hass: HomeAssistant,
    validating: AsyncMock,
    entry_data: dict[str, Any],
    tcp_form: dict[str, Any],
) -> None:
    """A reachable sensor produces an entry titled after its model."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "tcp"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "tcp"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], tcp_form)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "MTD062-MB (5.8 GHz)"
    assert result["data"] == entry_data
    assert result["result"].unique_id == "tcp:192.168.1.50:502#1"
    validating.assert_awaited_once()


async def test_serial_entry_is_created(hass: HomeAssistant, validating: AsyncMock) -> None:
    """An untouched form submits the factory link: 9600, no parity, one stop bit."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "serial"}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "device": "/dev/ttyUSB0",
            CONF_UNIT_ID: 3,
            CONF_MODEL: MODEL_MTD262,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TYPE] == TYPE_SERIAL
    assert result["data"][CONF_BAUDRATE] == DEFAULT_BAUDRATE
    assert result["data"][CONF_PARITY] == "N"
    assert result["data"][CONF_STOPBITS] == 1
    assert result["result"].unique_id == "serial:/dev/ttyUSB0:9600:N:1#3"


@pytest.mark.parametrize(
    "stopbits",
    [
        pytest.param("1", id="string-from-the-selector"),
        pytest.param(1, id="number-from-the-frontend"),
    ],
)
async def test_stop_bits_are_accepted_in_either_form(
    hass: HomeAssistant, validating: AsyncMock, stopbits: str | int
) -> None:
    """A browser sends the option as a string, a test or a script may send a number."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "serial"}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "device": "/dev/ttyUSB0",
            CONF_STOPBITS: stopbits,
            CONF_UNIT_ID: 3,
            CONF_MODEL: MODEL_MTD262,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STOPBITS] == 1


async def test_unreachable_sensor_shows_an_error(
    hass: HomeAssistant, tcp_form: dict[str, Any]
) -> None:
    """A silent sensor keeps the form open with an error, and creates nothing."""
    with patch(VALIDATE, new_callable=AsyncMock, side_effect=ModbusTimeoutError()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "tcp"}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], tcp_form)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_link_conflict_shows_its_own_error(
    hass: HomeAssistant, tcp_form: dict[str, Any]
) -> None:
    """The modbus integration refuses a second set of link settings; we say so."""
    with patch(
        VALIDATE,
        new_callable=AsyncMock,
        side_effect=HomeAssistantError("different settings"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "tcp"}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], tcp_form)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "connection_conflict"}


async def test_adding_the_same_sensor_twice_aborts(
    hass: HomeAssistant,
    validating: AsyncMock,
    mock_entry: MockConfigEntry,
    tcp_form: dict[str, Any],
) -> None:
    """One sensor on one link is one entry."""
    mock_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "tcp"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], tcp_form)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_changes_the_bus_address(
    hass: HomeAssistant,
    validating: AsyncMock,
    mock_entry: MockConfigEntry,
    tcp_form: dict[str, Any],
) -> None:
    """Changing the address keeps the entry and its entities."""
    mock_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": mock_entry.entry_id},
    )
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**tcp_form, CONF_UNIT_ID: 5}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_entry.data[CONF_UNIT_ID] == 5
    assert mock_entry.unique_id == "tcp:192.168.1.50:502#5"


async def test_validation_reads_through_a_unit_nobody_holds(
    hass: HomeAssistant, tcp_form: dict[str, Any], seed_readings: MockModbusUnit
) -> None:
    """The setup check runs on a temporary unit, not on a stored entry."""
    seen: dict[str, Any] = {}

    @asynccontextmanager
    async def temporary_unit(
        hass: HomeAssistant, params: Mapping[str, Any], unit_id: int
    ) -> AsyncIterator[MockModbusUnit]:
        seen["unit_id"] = unit_id
        yield seed_readings

    with patch("custom_components.mtdx62.config_flow.async_get_temporary_unit", temporary_unit):
        await _async_validate(hass, {CONF_TYPE: TYPE_TCP, **tcp_form, CONF_UNIT_ID: 7})

    assert seen["unit_id"] == 7


async def test_reconfigure_refuses_a_sensor_another_entry_already_has(
    hass: HomeAssistant,
    validating: AsyncMock,
    mock_entry: MockConfigEntry,
    tcp_form: dict[str, Any],
) -> None:
    """Two entries must not end up describing the same device on the bus."""
    mock_entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN,
        title="MTD262-MB (24 GHz)",
        data={**tcp_form, CONF_UNIT_ID: 2},
        unique_id="tcp:192.168.1.50:502#2",
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": mock_entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**tcp_form, CONF_UNIT_ID: 2}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_entry.data[CONF_UNIT_ID] == 1
