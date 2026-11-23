"""Test the buttons and managing commands."""

import pytest
from homeassistant.components.infrared import InfraredReceivedSignal
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.infrared.common import (
    MockInfraredEmitterEntity,
    MockInfraredReceiverEntity,
)

from .conftest import RAW, VOL_UP, nec


@pytest.fixture
async def setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> MockConfigEntry:
    """Set up the remote."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


async def test_entities(
    hass: HomeAssistant, setup: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    """There is a button per command and no remote entity."""
    assert hass.states.get("button.living_room_tv_power")
    assert hass.states.get("button.living_room_tv_volume_up")
    assert not hass.states.async_entity_ids("remote")


async def test_old_remote_entity_removed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    entity_registry: er.EntityRegistry,
) -> None:
    """A remote entity left over from an earlier version is removed."""
    mock_config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "remote",
        "custom_infrared_remote",
        mock_config_entry.entry_id,
        config_entry=mock_config_entry,
        suggested_object_id="living_room_tv",
    )
    assert entity_registry.async_get("remote.living_room_tv")
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get("remote.living_room_tv") is None


async def test_button_press(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
) -> None:
    """A button sends its command."""
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.living_room_tv_volume_up"},
        blocking=True,
    )
    assert (
        mock_infrared_emitter_entity.send_command_calls[0].get_raw_timings() == VOL_UP
    )


async def test_options_menu(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    """The menu shows the buttons."""
    result = await hass.config_entries.options.async_init(setup.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == [
        "learn_more",
        "relearn",
        "rename",
        "delete",
        "settings",
    ]
    assert result["description_placeholders"]["learned"] == "Power, Volume up"


async def test_options_learn_more(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Learn a new button from the options flow; existing ones stay."""
    result = await hass.config_entries.options.async_init(setup.entry_id)
    flow_id = result["flow_id"]
    result = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "learn_more"}
    )
    assert result["step_id"] == "command_name"
    result = await hass.config_entries.options.async_configure(
        flow_id, {"name": "Mute"}
    )
    mock_infrared_receiver_entity._handle_received_signal(InfraredReceivedSignal(RAW))
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_configure(flow_id)
    assert result["step_id"] == "review"
    result = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "save_finish"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert [c["name"] for c in setup.options["commands"]] == [
        "Power",
        "Volume up",
        "Mute",
    ]
    assert hass.states.get("button.living_room_tv_mute")


async def test_options_relearn(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    entity_registry: er.EntityRegistry,
) -> None:
    """Re-learning keeps the name, id and entity."""
    entity_id = "button.living_room_tv_power"
    unique_id = entity_registry.async_get(entity_id).unique_id
    result = await hass.config_entries.options.async_init(setup.entry_id)
    flow_id = result["flow_id"]
    result = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "relearn"}
    )
    result = await hass.config_entries.options.async_configure(
        flow_id, {"command": "p"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    mock_infrared_receiver_entity._handle_received_signal(
        InfraredReceivedSignal(nec(0x0A))
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_configure(flow_id)
    assert result["menu_options"] == ["test", "save_finish", "retry"]
    result = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "save_finish"}
    )
    await hass.async_block_till_done()
    power = setup.options["commands"][0]
    assert (power["id"], power["name"], power["timings"]) == ("p", "Power", nec(0x0A))
    assert entity_registry.async_get(entity_id).unique_id == unique_id


async def test_options_rename(
    hass: HomeAssistant, setup: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    """Renaming keeps the entity ID."""
    result = await hass.config_entries.options.async_init(setup.entry_id)
    flow_id = result["flow_id"]
    await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "rename"}
    )
    result = await hass.config_entries.options.async_configure(
        flow_id, {"Power": "Louder", "Volume up": "louder"}
    )
    assert result["errors"] == {"base": "name_exists"}
    result = await hass.config_entries.options.async_configure(
        flow_id, {"Power": "On/off", "Volume up": "Louder"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    state = hass.states.get("button.living_room_tv_power")
    assert state.name == "Living room TV On/off"
    assert (
        hass.states.get("button.living_room_tv_volume_up").name
        == "Living room TV Louder"
    )


async def test_options_delete(hass: HomeAssistant, setup: MockConfigEntry) -> None:
    """Delete buttons from the options flow."""
    result = await hass.config_entries.options.async_init(setup.entry_id)
    flow_id = result["flow_id"]
    await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "delete"}
    )
    result = await hass.config_entries.options.async_configure(
        flow_id, {"commands": ["v"]}
    )
    await hass.async_block_till_done()
    assert [c["name"] for c in setup.options["commands"]] == ["Power"]
    assert hass.states.get("button.living_room_tv_volume_up") is None
