"""Test setting up a remote: pick the type, name it, then learn on the screen."""

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant.components.infrared import (
    EMITTER_ENTITY_ID,
    RECEIVER_ENTITY_ID,
)

from custom_components.custom_infrared_remote.const import (
    CONF_DEVICE_TYPE,
    CONF_EMITTER,
    CONF_RECEIVER,
    DOMAIN,
)


@pytest.mark.usefixtures(
    "mock_infrared_emitter_entity", "mock_infrared_receiver_entity"
)
async def test_create_tv(hass: HomeAssistant) -> None:
    """A TV is created with only the common buttons suggested."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
        "tv",
        "projector",
        "speaker",
        "fan",
        "blinds",
        "screen",
        "generic",
    ]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "tv"}
    )
    assert result["step_id"] == "details"
    keys = {str(k): k for k in result["data_schema"].schema}
    assert keys[CONF_NAME].description == {"suggested_value": "TV"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Living room TV",
            CONF_EMITTER: EMITTER_ENTITY_ID,
            CONF_RECEIVER: RECEIVER_ENTITY_ID,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_TYPE] == "tv"
    assert result["options"]["commands"] == []
    hidden = result["options"]["hidden_roles"]
    assert "power" not in hidden
    assert "volume_up" not in hidden
    assert "channel_up" in hidden
    entry = result["result"]
    # The link at the end of setup opens the learning screen for this remote
    assert result["description_placeholders"]["link"] == (
        f"/custom-infrared-remote/{entry.unique_id}"
    )
    await hass.async_block_till_done()


@pytest.mark.usefixtures(
    "mock_infrared_emitter_entity", "mock_infrared_receiver_entity"
)
async def test_create_generic(hass: HomeAssistant) -> None:
    """Something else has no suggested buttons."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "generic"}
    )
    keys = {str(k): k for k in result["data_schema"].schema}
    assert keys[CONF_NAME].description is None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Soundbar",
            CONF_EMITTER: EMITTER_ENTITY_ID,
            CONF_RECEIVER: RECEIVER_ENTITY_ID,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {"commands": [], "hidden_roles": []}
    await hass.async_block_till_done()


@pytest.mark.usefixtures("init_infrared")
async def test_no_emitters(hass: HomeAssistant) -> None:
    """Abort without emitters."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["reason"] == "no_emitters"


@pytest.mark.usefixtures("mock_infrared_emitter_entity")
async def test_no_receivers(hass: HomeAssistant) -> None:
    """Abort without receivers."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["reason"] == "no_receivers"
