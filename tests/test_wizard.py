"""Test the guided wizard and the device types it creates."""

import asyncio

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.infrared import InfraredReceivedSignal
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import ATTR_ENTITY_ID, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.components.infrared import (
    EMITTER_ENTITY_ID,
    RECEIVER_ENTITY_ID,
)
from pytest_homeassistant.components.infrared.common import (
    MockInfraredEmitterEntity,
    MockInfraredReceiverEntity,
)

from custom_components.custom_infrared_remote.const import (
    CAPTURE_TIMEOUT,
    CONF_DEVICE_TYPE,
    CONF_EMITTER,
    CONF_RECEIVER,
    DOMAIN,
)
from custom_components.custom_infrared_remote.templates import get_template

from .conftest import nec

POWER = nec(0x08)
VOL_UP = nec(0x02)
VOL_DOWN = nec(0x03)
MUTE = nec(0x09)
HDMI_1 = nec(0x20)
CH_UP = nec(0x30)


async def _settle(hass: HomeAssistant) -> None:
    """Let callbacks run without waiting for the next capture to time out."""
    for _ in range(20):
        await asyncio.sleep(0)


async def _press(hass, receiver, flow_id, timings):
    receiver._handle_received_signal(InfraredReceivedSignal(timings))
    await _settle(hass)
    return await hass.config_entries.flow.async_configure(flow_id)


async def _start_tv(hass: HomeAssistant, buttons: list[str]):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    flow_id = result["flow_id"]
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "tv"}
    )
    assert result["step_id"] == "details"
    schema_keys = {str(k): k for k in result["data_schema"].schema}
    assert schema_keys[CONF_NAME].description == {"suggested_value": "TV"}

    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_NAME: "Living room TV",
            CONF_EMITTER: EMITTER_ENTITY_ID,
            CONF_RECEIVER: RECEIVER_ENTITY_ID,
        },
    )
    assert result["step_id"] == "buttons"
    assert (
        "/api/custom_infrared_remote/remote/tv.svg?"
        in (result["description_placeholders"]["image"])
    )
    sections = result["data_schema"].schema
    assert [str(k) for k in sections] == [
        "power",
        "volume",
        "channels",
        "inputs",
        "playback",
        "navigation",
    ]
    defaults = {
        str(k): next(iter(v.schema.schema)).default() for k, v in sections.items()
    }
    assert defaults["power"] == ["power"]
    assert defaults["volume"] == ["volume_up", "volume_down", "mute"]
    assert defaults["navigation"] == []
    collapsed = {str(k): v.options["collapsed"] for k, v in sections.items()}
    assert collapsed["volume"] is False
    assert collapsed["navigation"] is True

    template = get_template("tv")
    grouped: dict[str, dict[str, list[str]]] = {}
    for key in buttons:
        grouped.setdefault(template.role(key).group, {"buttons": []})["buttons"].append(
            key
        )
    result = await hass.config_entries.flow.async_configure(flow_id, grouped)
    return flow_id, result


@pytest.mark.usefixtures("mock_infrared_emitter_entity")
async def test_tv_wizard(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Pick a TV, press the buttons in turn, end with a media player."""
    receiver = mock_infrared_receiver_entity
    flow_id, result = await _start_tv(
        hass,
        ["power", "volume_up", "volume_down", "mute", "channel_up", "source_hdmi_1"],
    )

    # Buttons come in template order, and the wizard moves on by itself
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "press_button"
    assert result["description_placeholders"]["name"] == "Power"
    assert result["description_placeholders"]["position"] == "1"
    assert result["description_placeholders"]["total"] == "6"

    result = await _press(hass, receiver, flow_id, POWER)
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["step_id"] == "capture_next"
    assert result["description_placeholders"]["name"] == "Volume up"
    assert "✓ Power" in result["description_placeholders"]["checklist"]

    result = await _press(hass, receiver, flow_id, VOL_UP)
    assert result["description_placeholders"]["name"] == "Volume down"

    # Wrong button: the same as Power, so the wizard stops and asks
    result = await _press(hass, receiver, flow_id, POWER)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "capture_duplicate"
    placeholders = result["description_placeholders"]
    assert (placeholders["name"], placeholders["duplicate"]) == ("Volume down", "Power")
    assert "current=volume_down&waiting=0&done=power,volume_up" in placeholders["image"]
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "capture_retry"}
    )
    assert result["description_placeholders"]["name"] == "Volume down"
    result = await _press(hass, receiver, flow_id, VOL_DOWN)
    assert result["description_placeholders"]["name"] == "Mute"

    # Nothing pressed for Mute: the wizard asks, and it is skipped
    freezer.tick(CAPTURE_TIMEOUT + 1)
    async_fire_time_changed(hass)
    await _settle(hass)
    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["step_id"] == "capture_missed"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "capture_skip"}
    )
    assert result["description_placeholders"]["name"] == "Channel up"
    assert "Mute (skipped)" in result["description_placeholders"]["checklist"]

    result = await _press(hass, receiver, flow_id, CH_UP)
    result = await _press(hass, receiver, flow_id, HDMI_1)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "ready"
    assert result["menu_options"] == [
        "ready_test",
        "ready_relearn",
        "ready_more",
        "ready_custom",
        "ready_finish",
    ]
    placeholders = result["description_placeholders"]
    assert placeholders["controls"] == "Power, Volume up, Volume down, HDMI 1"
    assert placeholders["buttons"] == "Channel up"

    # Test a button from the ready menu
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "ready_test"}
    )
    power_id = next(
        o["value"]
        for o in result["data_schema"].schema["button"].config["options"]
        if o["label"] == "Power"
    )
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"button": power_id}
    )
    assert "Sent **Power**" in result["description_placeholders"]["note"]
    assert mock_infrared_emitter_entity.send_command_calls[-1].get_raw_timings() == (
        POWER
    )

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "ready_finish"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_TYPE] == "tv"
    roles = [c.get("role") for c in result["options"]["commands"]]
    assert roles == ["power", "volume_up", "volume_down", "channel_up", "source_hdmi_1"]
    await hass.async_block_till_done()

    # One media player for the TV controls, a button only for Channel up
    entry = result["result"]
    entity_ids = sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    )
    assert entity_ids == [
        "button.living_room_tv_channel_up",
        "event.living_room_tv_remote_button",
        "media_player.living_room_tv",
    ]
    state = hass.states.get("media_player.living_room_tv")
    assert state.attributes["device_class"] == "tv"
    assert state.attributes["source_list"] == ["HDMI 1"]
    assert state.attributes["assumed_state"] is True


async def test_relearn_from_ready(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """A button learned wrong can be pressed again from the ready menu."""
    receiver = mock_infrared_receiver_entity
    flow_id, result = await _start_tv(hass, ["power", "mute"])
    await _press(hass, receiver, flow_id, nec(0x55))
    result = await _press(hass, receiver, flow_id, MUTE)
    assert result["step_id"] == "ready"

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "ready_relearn"}
    )
    power_id = next(
        o["value"]
        for o in result["data_schema"].schema["button"].config["options"]
        if o["label"] == "Power"
    )
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"button": power_id}
    )
    assert result["description_placeholders"]["name"] == "Power"
    assert result["description_placeholders"]["total"] == "1"
    result = await _press(hass, receiver, flow_id, POWER)
    assert result["step_id"] == "ready"

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"next_step_id": "ready_finish"}
    )
    power = result["options"]["commands"][0]
    assert (power["id"], power["name"], power["timings"]) == (power_id, "Power", POWER)


def _entry(device_type: str, commands: dict[str, list[int]]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Thing",
        entry_id="thing",
        data={
            CONF_EMITTER: EMITTER_ENTITY_ID,
            CONF_RECEIVER: RECEIVER_ENTITY_ID,
            CONF_DEVICE_TYPE: device_type,
        },
        options={
            "commands": [
                {
                    "id": role,
                    "role": role,
                    "name": get_template(device_type).role(role).name,
                    "timings": timings,
                    "modulation": 38000,
                }
                for role, timings in commands.items()
            ]
        },
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _sent(emitter: MockInfraredEmitterEntity) -> list[list[int]]:
    sent = [c.get_raw_timings() for c in emitter.send_command_calls]
    emitter.send_command_calls.clear()
    return sent


async def test_media_player(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Media player services send the learned buttons."""
    emitter = mock_infrared_emitter_entity
    await _setup(
        hass,
        _entry(
            "tv",
            {
                "power": POWER,
                "volume_up": VOL_UP,
                "mute": MUTE,
                "source_hdmi_1": HDMI_1,
            },
        ),
    )
    entity_id = "media_player.thing"
    assert hass.states.get(entity_id).state == "unknown"

    async def call(service, **data):
        await hass.services.async_call(
            "media_player",
            service,
            {ATTR_ENTITY_ID: entity_id, **data},
            blocking=True,
        )

    # Power is a toggle: it is sent when the TV might be off, not when it's on
    await call("turn_on")
    assert _sent(emitter) == [POWER]
    assert hass.states.get(entity_id).state == "on"
    await call("turn_on")
    assert _sent(emitter) == []

    await call("volume_up")
    await call("volume_mute", is_volume_muted=True)
    await call("select_source", source="HDMI 1")
    assert _sent(emitter) == [VOL_UP, MUTE, HDMI_1]
    assert hass.states.get(entity_id).attributes["source"] == "HDMI 1"

    await call("turn_off")
    assert _sent(emitter) == [POWER]
    assert hass.states.get(entity_id).state == "off"


async def test_media_player_discrete_power(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Separate Power on and Power off are always sent."""
    await _setup(hass, _entry("tv", {"power_on": nec(0x40), "power_off": nec(0x41)}))
    for _ in range(2):
        await hass.services.async_call(
            "media_player",
            "turn_on",
            {ATTR_ENTITY_ID: "media_player.thing"},
            blocking=True,
        )
    assert _sent(mock_infrared_emitter_entity) == [nec(0x40), nec(0x40)]


async def test_fan(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """A fan with power and oscillate; speed buttons stay buttons."""
    emitter = mock_infrared_emitter_entity
    await _setup(
        hass,
        _entry(
            "fan",
            {"power": POWER, "oscillate": nec(0x50), "speed_up": nec(0x51)},
        ),
    )
    assert hass.states.get("button.thing_speed_up")

    await hass.services.async_call(
        "fan", "turn_on", {ATTR_ENTITY_ID: "fan.thing"}, blocking=True
    )
    await hass.services.async_call(
        "fan",
        "oscillate",
        {ATTR_ENTITY_ID: "fan.thing", "oscillating": True},
        blocking=True,
    )
    await hass.services.async_call(
        "fan",
        "oscillate",
        {ATTR_ENTITY_ID: "fan.thing", "oscillating": True},
        blocking=True,
    )
    assert _sent(emitter) == [POWER, nec(0x50)]
    state = hass.states.get("fan.thing")
    assert state.state == "on"
    assert state.attributes["oscillating"] is True


async def test_cover(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Open, close and stop send their buttons and stay available."""
    await _setup(
        hass,
        _entry("blinds", {"open": nec(0x60), "close": nec(0x61), "stop": nec(0x62)}),
    )
    for service in ("open_cover", "close_cover", "stop_cover"):
        await hass.services.async_call(
            "cover", service, {ATTR_ENTITY_ID: "cover.thing"}, blocking=True
        )
    assert _sent(mock_infrared_emitter_entity) == [nec(0x60), nec(0x61), nec(0x62)]
    state = hass.states.get("cover.thing")
    assert state.attributes["device_class"] == "blind"
    assert not hass.states.async_entity_ids("button")


async def test_options_learn_more_suggests_missing(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Learning more on a TV offers the suggested buttons not learned yet."""
    entry = _entry("tv", {"power": POWER})
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "learn_more"}
    )
    assert result["step_id"] == "buttons"
    sections = {str(k): v for k, v in result["data_schema"].schema.items()}
    power_key, power_selector = next(iter(sections["power"].schema.schema.items()))
    values = [o["value"] for o in power_selector.config["options"]]
    assert values == ["power_on", "power_off"]
    # Nothing ticked by default once the device has buttons
    assert power_key.default() == []


def test_remote_image() -> None:
    """The drawn remote highlights the current button and ticks learned ones."""
    from custom_components.custom_infrared_remote.illustrations import render_remote

    svg = render_remote(
        "tv",
        current="volume_up",
        done=frozenset({"power"}),
        queued=frozenset({"power", "volume_up"}),
        waiting=True,
    )
    assert svg.startswith("<svg")
    assert svg.count("<animate") == 4  # pulse on the button plus three beams
    assert "#2e9d4f" in svg  # Power learned
    assert render_remote("tv", current="power").count("<animate") == 1
    assert render_remote("generic") is None
    assert render_remote("../etc") is None


async def test_remote_image_view(hass: HomeAssistant, hass_client_no_auth) -> None:
    """The image is served without authentication, and only for known types."""
    from homeassistant.setup import async_setup_component

    from custom_components.custom_infrared_remote.illustrations import (
        async_register_view,
    )

    assert await async_setup_component(hass, "http", {})
    async_register_view(hass)
    client = await hass_client_no_auth()
    resp = await client.get(
        "/api/custom_infrared_remote/remote/fan.svg?current=power&done=&queued=power"
    )
    assert resp.status == 200
    assert resp.content_type == "image/svg+xml"
    resp = await client.get("/api/custom_infrared_remote/remote/generic.svg")
    assert resp.status == 404
