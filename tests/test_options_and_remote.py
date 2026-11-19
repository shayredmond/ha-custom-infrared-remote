"""Test managing commands and the remote entity."""

import asyncio

import pytest
from homeassistant.components.infrared import InfraredReceivedSignal
from homeassistant.components.remote import DOMAIN as REMOTE_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.infrared.common import (
    MockInfraredEmitterEntity,
    MockInfraredReceiverEntity,
)

from .conftest import POWER, RAW, VOL_UP, nec

REMOTE = "remote.living_room_tv"


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
    """The remote lists its buttons and is hidden by default."""
    state = hass.states.get(REMOTE)
    assert state.attributes["commands"] == ["Power", "Volume up"]
    assert hass.states.get("button.living_room_tv_power")
    assert (
        entity_registry.async_get(REMOTE).hidden_by is er.RegistryEntryHider.INTEGRATION
    )
    assert not entity_registry.async_get("button.living_room_tv_power").hidden_by


@pytest.mark.parametrize("service", ["turn_on", "turn_off"])
async def test_on_off_not_supported(
    hass: HomeAssistant, setup: MockConfigEntry, service: str
) -> None:
    """On and off give a clear error instead of failing."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            REMOTE_DOMAIN, service, {ATTR_ENTITY_ID: REMOTE}, blocking=True
        )
    assert err.value.translation_key == "on_off_not_supported"


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


async def test_send_command(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
) -> None:
    """remote.send_command sends by name, case does not matter, with repeats."""
    await hass.services.async_call(
        REMOTE_DOMAIN,
        "send_command",
        {
            ATTR_ENTITY_ID: REMOTE,
            "command": ["power", "Volume up"],
            "num_repeats": 2,
            "delay_secs": 0,
        },
        blocking=True,
    )
    sent = [
        c.get_raw_timings() for c in mock_infrared_emitter_entity.send_command_calls
    ]
    assert sent == [POWER, VOL_UP, POWER, VOL_UP]


async def test_send_unknown_command(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
) -> None:
    """A typo sends nothing and says which buttons exist."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            REMOTE_DOMAIN,
            "send_command",
            {ATTR_ENTITY_ID: REMOTE, "command": ["Power", "Mute"]},
            blocking=True,
        )
    assert err.value.translation_placeholders == {
        "command": "Mute",
        "commands": "Power, Volume up",
    }
    assert mock_infrared_emitter_entity.send_command_calls == []


async def test_learn_command_service(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """remote.learn_command adds new buttons and replaces existing ones."""
    call = hass.async_create_task(
        hass.services.async_call(
            REMOTE_DOMAIN,
            "learn_command",
            {ATTR_ENTITY_ID: REMOTE, "command": ["Mute", "Power"]},
            blocking=True,
        )
    )
    for timings in (RAW, nec(0x09)):
        await asyncio.sleep(0.01)
        mock_infrared_receiver_entity._handle_received_signal(
            InfraredReceivedSignal(timings)
        )
    await call
    await hass.async_block_till_done()

    commands = setup.options["commands"]
    assert [c["name"] for c in commands] == ["Power", "Volume up", "Mute"]
    assert commands[0]["id"] == "p"
    assert commands[0]["timings"] == nec(0x09)
    assert hass.states.get("button.living_room_tv_mute")


async def test_delete_command_service(
    hass: HomeAssistant, setup: MockConfigEntry
) -> None:
    """remote.delete_command removes buttons."""
    await hass.services.async_call(
        REMOTE_DOMAIN,
        "delete_command",
        {ATTR_ENTITY_ID: REMOTE, "command": ["power"]},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert [c["name"] for c in setup.options["commands"]] == ["Volume up"]
    assert hass.states.get("button.living_room_tv_power") is None


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
    assert hass.states.get(REMOTE).attributes["commands"] == ["On/off", "Louder"]


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
