"""Poll the sensor and decide when it counts as unavailable."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from modbus_connection import ModbusError
from mtdx62_modbus_library import DeviceStatus, Mtdx62Device, Readings

from .const import (
    DOMAIN,
    ISSUE_SELF_CHECK_STUCK,
    MAX_CONSECUTIVE_FAILURES,
    SCAN_INTERVAL,
    SELF_CHECK_STUCK_AFTER,
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

        self._log_fault()
        self._track_self_check()
        return self.device.readings

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

    @callback
    def async_clear_repairs(self) -> None:
        """Drop the repair issue once the sensor moved on, or the entry unloaded."""
        if not self._self_check_issue_raised:
            return
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_SELF_CHECK_STUCK)
        self._self_check_issue_raised = False
