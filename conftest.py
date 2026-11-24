"""Pytest configuration for the integration repository.

The Home Assistant test harness must be loaded as a plugin from the root of the
test run: pytest refuses to accept ``pytest_plugins`` in a nested conftest, and
with it they land in the wrong directory.
"""

from __future__ import annotations

pytest_plugins = "pytest_homeassistant_custom_component"
