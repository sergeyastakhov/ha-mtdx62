"""Shared fixtures for the MTDx62 tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtdx62.const import (
    CONF_MODEL,
    CONF_TYPE,
    CONF_UNIT_ID,
    DOMAIN,
    MODEL_MTD062,
    TYPE_TCP,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    """Let the harness load this custom component in every test."""
    yield


@pytest.fixture
def entry_data() -> dict[str, object]:
    """Link settings of one sensor on a TCP gateway."""
    return {
        CONF_TYPE: TYPE_TCP,
        "host": "192.168.1.50",
        "port": 502,
        CONF_UNIT_ID: 1,
        CONF_MODEL: MODEL_MTD062,
    }


@pytest.fixture
def tcp_form(entry_data: dict[str, object]) -> dict[str, object]:
    """What the user submits on the TCP step: link settings without the transport marker."""
    return {key: value for key, value in entry_data.items() if key != CONF_TYPE}


@pytest.fixture
def mock_entry(entry_data: dict[str, object]) -> MockConfigEntry:
    """A config entry describing that sensor."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="MTD062-MB (5.8 GHz)",
        data=entry_data,
        unique_id="tcp:192.168.1.50:502#1",
    )


@pytest.fixture
def mock_unit() -> MockModbusUnit:
    """A unit whose registers can be seeded per test."""
    from modbus_connection.mock import MockModbusConnection

    return MockModbusConnection().for_unit(1)


@pytest.fixture
def seed_readings(mock_unit: MockModbusUnit) -> MockModbusUnit:
    """Put a person in the room at 2.5 metres in dim light, sensor self-test passed."""
    mock_unit.input[0] = [1, 42, 250, 1, 0x0001, 0x0203, 0x0000, 0x0102]
    return mock_unit


SETUP = "custom_components.mtdx62.async_get_unit"


@pytest.fixture(autouse=True)
def patched_unit(seed_readings: MockModbusUnit) -> Generator[MockModbusUnit]:
    """Hand the integration a unit whose registers are already seeded.

    Autouse: any test that creates an entry lets Home Assistant set it up, and
    without the mock the integration asks the modbus component for a real unit,
    which opens a socket that the test harness blocks on purpose.
    """
    with patch(SETUP, return_value=seed_readings):
        yield seed_readings
