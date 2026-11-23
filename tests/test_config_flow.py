"""Test creating a remote and learning several buttons in one go."""

import asyncio
import json

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.infrared import InfraredReceivedSignal
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import async_fire_time_changed
from pytest_homeassistant.components.infrared import (
    EMITTER_ENTITY_ID,
    RECEIVER_ENTITY_ID,
)
from pytest_homeassistant.components.infrared.common import (
    MockInfraredEmitterEntity,
    MockInfraredReceiverEntity,
)

from custom_components.custom_infrared_remote.const import (
    CONF_EMITTER,
    CONF_RECEIVER,
    DOMAIN,
    LEARN_TIMEOUT,
)

from .conftest import POWER, RAW, VOL_UP, nec


async def _start_generic(hass):
    """Start the flow and pick Something else (a plain list of buttons)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "generic"}
    )


async def _press(hass, receiver, flow_id, timings, modulation=None):
    receiver._handle_received_signal(InfraredReceivedSignal(timings, modulation))
    await hass.async_block_till_done()
    return await hass.config_entries.flow.async_configure(flow_id)


async def test_full_flow(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Create a remote, learn two buttons, test one, end with one device."""
    receiver = mock_infrared_receiver_entity
    result = await _start_generic(hass)
    assert result["step_id"] == "details"
    flow_id = result["flow_id"]

    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_NAME: "Living room TV",
            CONF_EMITTER: EMITTER_ENTITY_ID,
            CONF_RECEIVER: RECEIVER_ENTITY_ID,
        },
    )
    assert result["step_id"] == "command_name"

    # Button 1, held down: repeats are removed
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NAME: "Power"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["description_placeholders"] == {"name": "Power"}

    # Noise is ignored, the flow keeps waiting
    # (no block_till_done here: it would wait for the learn task to time out)
    receiver._handle_received_signal(InfraredReceivedSignal([500, -500]))
    await asyncio.sleep(0)
    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["type"] is FlowResultType.SHOW_PROGRESS

    result = await _press(hass, receiver, flow_id, nec(0x08, repeats=3))
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "review"
    assert result["menu_options"] == ["test", "save_next", "save_finish", "retry"]
    placeholders = result["description_placeholders"]
    assert "NEC, address 0x04, command 0x08" in placeholders["summary"]
    assert "38 kHz (assumed)" in placeholders["summary"]
    assert "held the button" in placeholders["notes"]

    # Test it: the emitter gets exactly one frame
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "test"}
    )
    assert result["step_id"] == "review"
    assert "Sent" in result["description_placeholders"]["notes"]
    assert (
        mock_infrared_emitter_entity.send_command_calls[-1].get_raw_timings() == POWER
    )

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "save_next"}
    )
    assert result["step_id"] == "command_name"
    assert result["description_placeholders"]["learned"] == "Power"

    # Same name again is refused
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NAME: "power"}
    )
    assert result["errors"] == {CONF_NAME: "name_exists"}

    # Button 2, but the user pressed Power again: warned
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NAME: "Volume up"}
    )
    result = await _press(hass, receiver, flow_id, POWER)
    assert "same as **Power**" in result["description_placeholders"]["notes"]

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "retry"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    result = await _press(hass, receiver, flow_id, VOL_UP, modulation=40000)
    assert result["description_placeholders"]["notes"] == ""
    assert "40 kHz ·" not in result["description_placeholders"]["summary"]
    assert result["description_placeholders"]["summary"].endswith("40 kHz")

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "save_finish"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Living room TV"
    commands = result["options"]["commands"]
    assert [c["name"] for c in commands] == ["Power", "Volume up"]
    assert commands[0]["timings"] == POWER
    assert commands[1]["modulation"] == 40000
    await hass.async_block_till_done()

    # One device: an event entity and one button per command
    entry = result["result"]
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices) == 1
    entities = er.async_entries_for_device(entity_registry, devices[0].id)
    assert sorted(e.entity_id for e in entities) == [
        "button.living_room_tv_power",
        "button.living_room_tv_volume_up",
        "event.living_room_tv_remote_button",
    ]


async def test_finish_without_commands(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """An empty name finishes, so a remote can be created now and taught later."""
    result = await _start_generic(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Fan",
            CONF_EMITTER: EMITTER_ENTITY_ID,
            CONF_RECEIVER: RECEIVER_ENTITY_ID,
        },
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {"commands": [], "hidden_roles": []}


async def test_no_signal(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    freezer: FrozenDateTimeFactory,
) -> None:
    """On timeout the name form comes back with the name filled in."""
    result = await _start_generic(hass)
    flow_id = result["flow_id"]
    await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_NAME: "TV",
            CONF_EMITTER: EMITTER_ENTITY_ID,
            CONF_RECEIVER: RECEIVER_ENTITY_ID,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NAME: "Mute"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS

    freezer.tick(LEARN_TIMEOUT + 1)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["step_id"] == "command_name"
    assert result["errors"] == {"base": "no_signal"}

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NAME: "Mute"}
    )
    result = await _press(hass, mock_infrared_receiver_entity, flow_id, RAW)
    assert "Unknown protocol" in result["description_placeholders"]["summary"]


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


class _RepeatedScalar:
    """Stand-in for the protobuf container ESPHome receivers deliver timings in.

    It is iterable but not a list, and json cannot serialize it.
    """

    def __init__(self, values: list[int]) -> None:
        self._values = values

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]


async def test_protobuf_timings_are_stored_as_list(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Timings from ESPHome must be stored as a plain list, or entry storage breaks."""
    result = await _start_generic(hass)
    flow_id = result["flow_id"]
    await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_NAME: "TV",
            CONF_EMITTER: EMITTER_ENTITY_ID,
            CONF_RECEIVER: RECEIVER_ENTITY_ID,
        },
    )
    await hass.config_entries.flow.async_configure(flow_id, {CONF_NAME: "Power"})
    await _press(hass, mock_infrared_receiver_entity, flow_id, _RepeatedScalar(RAW))
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "save_finish"}
    )
    stored = result["options"]["commands"][0]["timings"]
    assert type(stored) is list
    json.dumps(result["options"])
