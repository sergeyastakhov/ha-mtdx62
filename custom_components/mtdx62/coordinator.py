"""Poll the sensor and decide when it counts as unavailable."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from modbus_connection import ModbusError, ModbusExceptionError
from mtdx62_modbus_library import (
    DeviceStatus,
    Mtdx62Device,
    Readings,
    WriteVerificationError,
)

from .const import (
    BUS_PARITY_OPTION_BY_CODE,
    DOMAIN,
    HEALTHY_STATUS_CODE,
    ISSUE_BUS_SETTINGS_CHANGED,
    ISSUE_SELF_CHECK_STUCK,
    MAX_CONSECUTIVE_FAILURES,
    SCAN_INTERVAL,
    SELF_CHECK_STUCK_AFTER,
    SETTINGS_EVERY,
)

_LOGGER = logging.getLogger(__name__)


class Mtdx62Coordinator(DataUpdateCoordinator[Readings]):
    """Read the sensor every few seconds and watch its health code."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device: Mtdx62Device) -> None:
        """Set up the coordinator for one sensor."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.device = device
        self._failures = 0
        self._unavailable_logged = False
        self._reported_fault: int | None = None
        self._self_check_since: datetime | None = None
        self._self_check_issue_raised = False
        self._polls = 0
        self._bus_issue_raised = False

    async def _async_update_data(self) -> Readings:
        """Read the measurements, tolerating a single lost frame."""
        try:
            await self.device.async_update_readings()
        except ModbusError as err:
            self._failures += 1
            if self._failures < MAX_CONSECUTIVE_FAILURES and self.data is not None:
                _LOGGER.debug("%s: poll %s failed, retrying: %s", self.name, self._failures, err)
                return self.data
            self._log_unavailable()
            raise UpdateFailed(f"cannot read {self.name}") from err

        if self._failures:
            self._failures = 0
            if self._unavailable_logged:
                _LOGGER.info("%s: sensor is answering again", self.name)
                self._unavailable_logged = False

        if self._bus_issue_raised:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_BUS_SETTINGS_CHANGED)
            self._bus_issue_raised = False

        await self._async_update_settings()
        self._log_fault()
        self._track_self_check()
        return self.device.readings

    async def _async_update_settings(self) -> None:
        """Read the parameters at start, then once a minute.

        They are changed by the infrared remote as well, so they have to be
        re-read; polling them at the measurement rate would double the traffic.
        A failed settings read must not mark the device unavailable: the
        measurements came through.
        """
        self._polls += 1
        if self._polls % SETTINGS_EVERY != 1:
            return
        try:
            await self.device.async_update_settings()
        except ModbusError as err:
            _LOGGER.debug("%s: could not read settings: %s", self.name, err)

    def _log_unavailable(self) -> None:
        """Say the sensor is gone once, not on every failed poll."""
        if not self._unavailable_logged:
            _LOGGER.warning(
                "%s: no answer after %s polls, marking unavailable",
                self.name,
                self._failures,
            )
            self._unavailable_logged = True

    def _log_fault(self) -> None:
        """Report a health code once when it appears and once when it clears.

        A running sensor reports 1; 0 is the transient self-check at power-up.
        Neither is a fault, so only codes from 2 upwards reach the log.
        """
        status = self.device.readings.status
        if status is None or not status.is_fault:
            if self._reported_fault is not None:
                _LOGGER.info("%s: health code back to normal", self.name)
                self._reported_fault = None
            return
        code = status.value
        if code != self._reported_fault:
            _LOGGER.warning("%s: sensor reports health code %s (%s)", self.name, code, status.name)
            self._reported_fault = code

    def _track_self_check(self) -> None:
        """Raise a repair when the self-check never finishes.

        The code 0 is normal for a moment after power-up. If it is still there a
        minute later, the sensor is not booting, and the user is the only one who
        can power-cycle it.
        """
        if self.device.readings.status_code != DeviceStatus.SELF_CHECK_IN_PROGRESS:
            self._self_check_since = None
            self.async_clear_repairs()
            return
        now = dt_util.utcnow()
        if self._self_check_since is None:
            self._self_check_since = now
            return
        if self._self_check_issue_raised or now - self._self_check_since < SELF_CHECK_STUCK_AFTER:
            return
        self._self_check_issue_raised = True
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_SELF_CHECK_STUCK,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_SELF_CHECK_STUCK,
            translation_placeholders={"name": self.config_entry.title},
        )

    async def async_write_setting(self, field: str, value: float | int) -> None:
        """Write one ordinary parameter, with the checks the sensor cannot do for us.

        The health code is taken from the last poll: it is at most five seconds
        old, and reading it again would double the traffic for a guard.
        """
        self._require_ready()
        self._require_zones_fit(field, value)
        try:
            await self.device.settings.async_write(field, value)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="value_out_of_range",
                translation_placeholders={"error": str(err)},
            ) from err
        except WriteVerificationError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="value_not_stored",
                translation_placeholders={
                    "requested": str(err.requested),
                    "stored": str(err.stored),
                },
            ) from err
        except ModbusExceptionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="device_rejected"
            ) from err
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_answer"
            ) from err
        self.async_update_listeners()

    async def async_write_link_settings(self, *, unit_id: int, baudrate: int, parity: int) -> None:
        """Write the three bus values in one request; the old link dies with it.

        There is no confirmation read on purpose: once the sensor accepts the
        values it answers elsewhere, and the old link is already silent. The entry
        keeps the old parameters, so the device becomes unreachable until the user
        runs the reconfigure flow; a repair says so.
        """
        try:
            await self.device.settings.async_write_link_settings(
                unit_id=unit_id, baudrate=baudrate, parity=parity
            )
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="value_out_of_range",
                translation_placeholders={"error": str(err)},
            ) from err
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_answer"
            ) from err
        _LOGGER.warning(
            "%s: the sensor now answers on address %s, %s baud, parity %s;"
            " this entry still uses the old link",
            self.name,
            unit_id,
            baudrate,
            parity,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_BUS_SETTINGS_CHANGED,
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_BUS_SETTINGS_CHANGED,
            translation_placeholders={
                "name": self.config_entry.title,
                "address": str(unit_id),
                "baudrate": str(baudrate),
                "parity": BUS_PARITY_OPTION_BY_CODE.get(parity, str(parity)),
            },
        )
        self._bus_issue_raised = True

    def _require_ready(self) -> None:
        """Refuse to write while the sensor is booting or broken."""
        code = None if self.data is None else self.data.status_code
        if code == HEALTHY_STATUS_CODE:
            return
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_not_ready",
            translation_placeholders={"code": "unknown" if code is None else str(code)},
        )

    def _require_zones_fit(self, field: str, value: float | int) -> None:
        """Check the rule the sensor enforces with an unhelpful exception 0x02."""
        settings = self.device.settings
        detection = value if field == "detection_distance" else settings.detection_distance
        shielding = value if field == "shielding_distance" else settings.shielding_distance
        indent = value if field == "entry_indent" else settings.entry_indent
        if detection is None or shielding is None or indent is None:
            return
        # A sensor that has not been read yet reports zeros; the rule means nothing
        # until there is a real range to fit the zones into.
        if float(detection) <= 0:
            return
        zones = round(float(shielding) + float(indent), 2)
        if zones < float(detection):
            return
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="zones_do_not_fit",
            translation_placeholders={
                "zones": f"{zones:g}",
                "detection": f"{float(detection):g}",
            },
        )

    @callback
    def async_clear_repairs(self) -> None:
        """Drop the repair issues once the sensor moved on, or the entry unloaded."""
        if self._bus_issue_raised:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_BUS_SETTINGS_CHANGED)
            self._bus_issue_raised = False
        if not self._self_check_issue_raised:
            return
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_SELF_CHECK_STUCK)
        self._self_check_issue_raised = False
