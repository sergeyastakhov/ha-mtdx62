"""Value mapping for the sensor entities, away from Home Assistant's plumbing."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from mtdx62_modbus_library import DeviceStatus, Readings

from custom_components.mtdx62.sensor import UNKNOWN_CODE, _distance_m, _status_key


def test_status_is_none_before_the_first_read() -> None:
    """An unread sensor reports nothing rather than a made-up code."""
    readings = Mock(spec=Readings)
    readings.status_code = None

    assert _status_key(readings) is None


def test_undocumented_status_code_is_shown_as_such() -> None:
    """A code the library does not know stays visible instead of looking healthy."""
    readings = Mock(spec=Readings)
    readings.status_code = 99
    readings.status = None

    assert _status_key(readings) == UNKNOWN_CODE


@pytest.mark.parametrize(
    ("status", "key"),
    [
        pytest.param(DeviceStatus.OK, "ok", id="ok"),
        pytest.param(
            DeviceStatus.SELF_CHECK_IN_PROGRESS, "self_check_in_progress", id="self-check"
        ),
        pytest.param(DeviceStatus.RADAR_AND_RS485_FAULT, "radar_and_rs485_fault", id="both-faults"),
    ],
)
def test_known_status_codes_map_to_their_translation_key(status: DeviceStatus, key: str) -> None:
    """Every documented code has a key the translations know."""
    readings = Mock(spec=Readings)
    readings.status_code = int(status)
    readings.status = status

    assert _status_key(readings) == key


def test_distance_without_a_target_is_none() -> None:
    """No target means no distance, not zero metres."""
    readings = Mock(spec=Readings)
    readings.distance = None

    assert _distance_m(readings) is None


def test_distance_keeps_the_library_metres() -> None:
    """No conversion happens here: the value is already metres with a centimetre step."""
    readings = Mock(spec=Readings)
    readings.distance = 2.51

    assert _distance_m(readings) == 2.51
