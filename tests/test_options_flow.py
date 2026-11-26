"""The switch that unlocks the bus settings."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mtdx62.const import CONF_ALLOW_BUS_SETTINGS, CONF_CONFIRM


async def test_bus_settings_are_off_by_default(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """The form asks, and saying no keeps the risky entities away."""
    mock_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ALLOW_BUS_SETTINGS: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options[CONF_ALLOW_BUS_SETTINGS] is False


async def test_enabling_needs_a_confirmation(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """A checkbox is not enough for an action that makes the sensor unreachable."""
    mock_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ALLOW_BUS_SETTINGS: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bus_settings_confirm"
    assert CONF_ALLOW_BUS_SETTINGS not in mock_entry.options

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONFIRM: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options[CONF_ALLOW_BUS_SETTINGS] is True


async def test_declining_the_confirmation_leaves_it_off(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """Changing your mind at the warning keeps the safe default."""
    mock_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ALLOW_BUS_SETTINGS: True}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONFIRM: False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_entry.options[CONF_ALLOW_BUS_SETTINGS] is False
