"""Unit tests for the small helpers the flow leans on."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant

from custom_components.mtdx62.const import CONF_TYPE, TYPE_SERIAL, TYPE_TCP
from custom_components.mtdx62.helpers import (
    CONNECTIONS_STORE,
    YAML_HUBS_STORE,
    held_serial_links,
    same_device_under_another_path,
    yaml_hub_for,
    yaml_hubs_using,
)


def serial(device: str) -> dict[str, Any]:
    """Form data for a serial link."""
    return {CONF_TYPE: TYPE_SERIAL, CONF_DEVICE: device}


def test_only_serial_links_are_listed(hass: HomeAssistant) -> None:
    """Network connections say nothing about a serial port."""
    hass.data[CONNECTIONS_STORE] = {
        ("serial", "/dev/ttyUSB0"): object(),
        ("tcp", "192.168.1.50:502"): object(),
    }

    assert held_serial_links(hass) == ["/dev/ttyUSB0"]


def test_nothing_is_held_without_a_store(hass: HomeAssistant) -> None:
    """A fresh Home Assistant has no connections at all."""
    assert held_serial_links(hass) == []
    assert same_device_under_another_path(hass, serial("/dev/ttyUSB0")) is None


def test_the_same_path_is_not_another_path(hass: HomeAssistant) -> None:
    """The port the user typed is not reported back as a different name."""
    hass.data[CONNECTIONS_STORE] = {("serial", "/dev/ttyUSB0"): object()}

    assert same_device_under_another_path(hass, serial("/dev/ttyUSB0")) is None


def test_a_symbolic_link_to_the_same_device_is_found(hass: HomeAssistant, tmp_path: Path) -> None:
    """`/dev/serial/by-id/...` and `/dev/ttyUSB0` are one device under two names."""
    device = tmp_path / "ttyUSB0"
    device.write_text("", encoding="utf-8")
    alias = tmp_path / "usb-adapter-port0"
    try:
        os.symlink(device, alias)
    except OSError, NotImplementedError:
        pytest.skip("this platform does not allow creating symbolic links")

    hass.data[CONNECTIONS_STORE] = {("serial", str(alias)): object()}

    assert same_device_under_another_path(hass, serial(str(device))) == str(alias)


def test_a_network_link_has_no_held_port(hass: HomeAssistant) -> None:
    """A TCP link cannot collide with a serial one."""
    hass.data[CONNECTIONS_STORE] = {("serial", "/dev/ttyUSB0"): object()}

    assert same_device_under_another_path(hass, {CONF_TYPE: TYPE_TCP}) is None


class FakeHub:
    """Enough of a legacy ModbusHub for the checks."""

    def __init__(self, port: str) -> None:
        """Remember the endpoint the hub was given."""
        self.endpoint = ("serial", port)


def test_yaml_hubs_are_listed_with_their_names(hass: HomeAssistant) -> None:
    """A YAML setup holds its port outside the shared registry."""
    hass.data[YAML_HUBS_STORE] = {"default": FakeHub("/dev/ttyAMA0")}

    assert yaml_hubs_using(hass) == [("default", "/dev/ttyAMA0")]


def test_the_hub_holding_the_same_port_is_named(hass: HomeAssistant) -> None:
    """Exactly the device submitted, held by a hub, is the clearest case."""
    hass.data[YAML_HUBS_STORE] = {"default": FakeHub("/dev/ttyAMA0")}

    assert yaml_hub_for(hass, serial("/dev/ttyAMA0")) == "default"
    assert yaml_hub_for(hass, serial("/dev/ttyAMA4")) is None
    assert yaml_hub_for(hass, {CONF_TYPE: TYPE_TCP}) is None


def test_a_hub_using_a_link_to_the_same_port_is_found(hass: HomeAssistant, tmp_path: Path) -> None:
    """`/dev/serial0` is usually a link to `/dev/ttyAMA0`, and the hub keeps its own name."""
    device = tmp_path / "ttyAMA0"
    device.write_text("", encoding="utf-8")
    alias = tmp_path / "serial0"
    try:
        os.symlink(device, alias)
    except OSError, NotImplementedError:
        pytest.skip("this platform does not allow creating symbolic links")

    hass.data[YAML_HUBS_STORE] = {"modbus_hub_0": FakeHub(str(alias))}

    assert yaml_hub_for(hass, serial(str(device))) == "modbus_hub_0"
