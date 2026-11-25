"""Constants for the MTDx62 presence sensor integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "mtdx62"
MANUFACTURER: Final = "Zhejiang Oujue Electronic Technology"

CONF_TYPE: Final = "type"
CONF_UNIT_ID: Final = "unit_id"
CONF_MODEL: Final = "model"
CONF_BAUDRATE: Final = "baudrate"
CONF_PARITY: Final = "parity"
CONF_STOPBITS: Final = "stopbits"

TYPE_TCP: Final = "tcp"
TYPE_SERIAL: Final = "serial"

DEFAULT_PORT: Final = 502
DEFAULT_BAUDRATE: Final = 9600
# The sensor ships with parity code 0 (no parity), which is also what it answered on
# the bench: 9600 8N1.
DEFAULT_PARITY: Final = "N"
DEFAULT_STOPBITS: Final = 1
DEFAULT_UNIT_ID: Final = 1

PARITY_OPTIONS: Final = ["N", "E", "O"]
STOPBIT_OPTIONS: Final = [1, 2]

MODEL_MTD062: Final = "mtd062-mb"
MODEL_MTD262: Final = "mtd262-mb"
MODELS: Final = {
    MODEL_MTD062: "MTD062-MB (5.8 GHz)",
    MODEL_MTD262: "MTD262-MB (24 GHz)",
}

# The sensor is polled every 5 seconds: fast enough for light-on-presence, and one
# register block read per device keeps a busy bus affordable.
SCAN_INTERVAL: Final = 5

# A single lost frame on an RS485 bus is ordinary; only a run of failures means
# the device is gone.
MAX_CONSECUTIVE_FAILURES: Final = 3

# The sensor reports 1 once its self-test passed. Any other code means it is still
# booting or broken, and its measurements are not trustworthy.
HEALTHY_STATUS_CODE: Final = 1

# A self-check that lasts longer than this is not booting any more, it is stuck.
SELF_CHECK_STUCK_AFTER: Final = timedelta(seconds=60)

ISSUE_SELF_CHECK_STUCK: Final = "self_check_stuck"

# Register spaces exposed by the library that diagnostics dumps in raw form.
RAW_DIAGNOSTIC_NAMES: Final = ("readings", "settings")

# Fields diagnostics reports from the settings sub-system.
SETTINGS_DIAGNOSTIC_FIELDS: Final = (
    "detection_distance",
    "shielding_distance",
    "entry_delay",
    "departure_delay",
    "trigger_sensitivity",
    "maintain_sensitivity",
    "entry_indent",
    "unit_id",
    "baudrate",
    "parity",
    "active_report",
    "light_threshold",
    "report_interval",
)
