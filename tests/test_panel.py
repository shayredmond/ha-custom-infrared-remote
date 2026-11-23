"""Test the learning screen's websocket API."""

import json

import pytest
from homeassistant.components.infrared import InfraredReceivedSignal
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.infrared import (
    EMITTER_ENTITY_ID,
    RECEIVER_ENTITY_ID,
)
from pytest_homeassistant.components.infrared.common import (
    MockInfraredEmitterEntity,
    MockInfraredReceiverEntity,
)

from custom_components.custom_infrared_remote.const import (
    CONF_DEVICE_TYPE,
    CONF_EMITTER,
    CONF_RECEIVER,
    DOMAIN,
)

from .conftest import RAW, nec

POWER = nec(0x08)
VOL_UP = nec(0x02)


class _RepeatedScalar:
    """Stand-in for the protobuf container ESPHome receivers deliver timings in."""

    def __init__(self, values: list[int]) -> None:
        self._values = values

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]


@pytest.fixture
async def tv(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> MockConfigEntry:
    """A TV with nothing learned, as the setup dialog creates it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="TV",
        entry_id="tv",
        unique_id="abc",
        data={
            CONF_EMITTER: EMITTER_ENTITY_ID,
            CONF_RECEIVER: RECEIVER_ENTITY_ID,
            CONF_DEVICE_TYPE: "tv",
        },
        options={"commands": [], "hidden_roles": ["channel_up", "home"]},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _get(client, entry_id="tv") -> dict:
    await client.send_json_auto_id({"type": f"{DOMAIN}/get", "entry_id": entry_id})
    msg = await client.receive_json()
    assert msg["success"], msg
    return msg["result"]


async def _call(client, **data) -> dict:
    await client.send_json_auto_id({"entry_id": "tv", **data})
    return await client.receive_json()


async def _capture(client) -> int:
    await client.send_json_auto_id({"type": f"{DOMAIN}/capture", "entry_id": "tv"})
    msg = await client.receive_json()
    assert msg["success"], msg
    return msg["id"]


async def _hear(hass, client, receiver, timings) -> dict:
    receiver._handle_received_signal(InfraredReceivedSignal(timings))
    msg = await client.receive_json()
    assert msg["type"] == "event"
    return msg["event"]


async def test_panel_registered(hass: HomeAssistant, tv: MockConfigEntry) -> None:
    """The screen is a hidden admin panel, linked from the device page."""
    panels = hass.data["frontend_panels"]
    panel = panels["custom-infrared-remote"]
    assert panel.require_admin
    assert not panel.show_in_sidebar
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "tv"), "tv")
    assert device.configuration_url == "homeassistant://custom-infrared-remote/tv"


async def test_get(hass: HomeAssistant, tv: MockConfigEntry, hass_ws_client) -> None:
    """The screen gets the suggested buttons, by entry ID or unique ID."""
    client = await hass_ws_client(hass)
    data = await _get(client)
    assert data["title"] == "TV"
    assert data["device_type"] == "tv"
    assert data["receiver"] == "Test IR receiver"
    roles = {r["key"]: r for r in data["roles"]}
    assert roles["power"] == {
        "key": "power",
        "name": "Power",
        "group": "power",
        "learned": False,
        "command_id": None,
        "hidden": False,
    }
    assert roles["channel_up"]["hidden"] is True
    assert data["custom"] == []
    assert (await _get(client, "abc"))["entry_id"] == "tv"

    await client.send_json_auto_id({"type": f"{DOMAIN}/get", "entry_id": "nope"})
    assert (await client.receive_json())["error"]["code"] == "not_found"


async def test_learn_in_turn(
    hass: HomeAssistant,
    tv: MockConfigEntry,
    hass_ws_client,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Captured presses are saved to the highlighted row; duplicates are flagged."""
    receiver = mock_infrared_receiver_entity
    client = await hass_ws_client(hass)
    await _capture(client)

    event = await _hear(hass, client, receiver, POWER)
    assert "NEC" in event["summary"]
    assert event["matches"] is None
    msg = await _call(
        client, type=f"{DOMAIN}/assign", token=event["token"], role="power"
    )
    assert "saved" in msg["result"]
    await hass.async_block_till_done()

    # Pressing Power again for Volume up: flagged, nothing saved
    event = await _hear(hass, client, receiver, POWER)
    assert event["matches"] == "Power"
    msg = await _call(
        client, type=f"{DOMAIN}/assign", token=event["token"], role="volume_up"
    )
    assert msg["result"] == {"duplicate": "Power"}
    # ...unless kept anyway
    msg = await _call(
        client,
        type=f"{DOMAIN}/assign",
        token=event["token"],
        role="volume_up",
        allow_duplicate=True,
    )
    assert "saved" in msg["result"]
    await hass.async_block_till_done()

    # Relearning Volume up keeps its ID
    roles = {r["key"]: r for r in (await _get(client))["roles"]}
    vol_id = roles["volume_up"]["command_id"]
    event = await _hear(hass, client, receiver, VOL_UP)
    msg = await _call(
        client, type=f"{DOMAIN}/assign", token=event["token"], role="volume_up"
    )
    assert msg["result"] == {"saved": vol_id}
    await hass.async_block_till_done()

    commands = tv.options["commands"]
    assert [(c["role"], c["timings"]) for c in commands] == [
        ("power", POWER),
        ("volume_up", VOL_UP),
    ]
    assert hass.states.get("media_player.tv")
    # Presses heard while learning don't fire the Remote button event
    assert hass.states.get("event.tv_remote_button").state == "unknown"


async def test_custom_buttons(
    hass: HomeAssistant,
    tv: MockConfigEntry,
    hass_ws_client,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
) -> None:
    """Your own buttons: add by name, relearn, test and delete."""
    receiver = mock_infrared_receiver_entity
    client = await hass_ws_client(hass)
    await _capture(client)

    event = await _hear(hass, client, receiver, RAW)
    msg = await _call(
        client, type=f"{DOMAIN}/assign", token=event["token"], name="Netflix"
    )
    command_id = msg["result"]["saved"]
    await hass.async_block_till_done()
    assert (await _get(client))["custom"] == [{"id": command_id, "name": "Netflix"}]
    assert hass.states.get("button.tv_netflix")

    event = await _hear(hass, client, receiver, POWER)
    msg = await _call(
        client, type=f"{DOMAIN}/assign", token=event["token"], name="netflix"
    )
    assert msg["error"]["code"] == "name_exists"

    msg = await _call(
        client, type=f"{DOMAIN}/assign", token=event["token"], command_id=command_id
    )
    assert msg["result"] == {"saved": command_id}
    await hass.async_block_till_done()

    msg = await _call(client, type=f"{DOMAIN}/test", command_id=command_id)
    assert msg["success"]
    assert mock_infrared_emitter_entity.send_command_calls[-1].get_raw_timings() == (
        POWER
    )

    msg = await _call(client, type=f"{DOMAIN}/delete", command_id=command_id)
    assert msg["success"]
    await hass.async_block_till_done()
    assert tv.options["commands"] == []
    assert hass.states.get("button.tv_netflix") is None


async def test_hide_and_show(
    hass: HomeAssistant,
    tv: MockConfigEntry,
    hass_ws_client,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Hiding forgets a learned button; showing brings it back to learn."""
    client = await hass_ws_client(hass)
    await _capture(client)
    event = await _hear(hass, client, mock_infrared_receiver_entity, POWER)
    await _call(client, type=f"{DOMAIN}/assign", token=event["token"], role="power")
    await hass.async_block_till_done()

    await _call(client, type=f"{DOMAIN}/hide", role="power", hidden=True)
    await hass.async_block_till_done()
    roles = {r["key"]: r for r in (await _get(client))["roles"]}
    assert roles["power"]["hidden"] is True
    assert roles["power"]["learned"] is False
    assert tv.options["commands"] == []

    await _call(client, type=f"{DOMAIN}/hide", role="channel_up", hidden=False)
    await hass.async_block_till_done()
    assert tv.options["hidden_roles"] == ["home", "power"]


async def test_capture_ignores_echo_and_noise(
    hass: HomeAssistant,
    tv: MockConfigEntry,
    hass_ws_client,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Sending a test press doesn't get captured as the next button."""
    receiver = mock_infrared_receiver_entity
    client = await hass_ws_client(hass)
    await _capture(client)
    event = await _hear(hass, client, receiver, POWER)
    msg = await _call(
        client, type=f"{DOMAIN}/assign", token=event["token"], name="Thing"
    )
    command_id = msg["result"]["saved"]
    await hass.async_block_till_done()

    await _call(client, type=f"{DOMAIN}/test", command_id=command_id)
    receiver._handle_received_signal(InfraredReceivedSignal(POWER))
    receiver._handle_received_signal(InfraredReceivedSignal([500, -500]))
    # The next message is the reply to this call, so nothing was captured
    msg = await _call(client, type=f"{DOMAIN}/delete", command_id="none")
    assert msg["type"] == "result"


async def test_protobuf_timings_are_stored_as_list(
    hass: HomeAssistant,
    tv: MockConfigEntry,
    hass_ws_client,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Timings from ESPHome must be stored as a plain list, or entry storage breaks."""
    client = await hass_ws_client(hass)
    await _capture(client)
    event = await _hear(
        hass, client, mock_infrared_receiver_entity, _RepeatedScalar(RAW)
    )
    await _call(client, type=f"{DOMAIN}/assign", token=event["token"], name="Raw")
    await hass.async_block_till_done()
    stored = tv.options["commands"][0]["timings"]
    assert type(stored) is list
    json.dumps(dict(tv.options))


async def test_expired_token(
    hass: HomeAssistant, tv: MockConfigEntry, hass_ws_client
) -> None:
    """An unknown capture asks for the button again."""
    client = await hass_ws_client(hass)
    msg = await _call(client, type=f"{DOMAIN}/assign", token="gone", role="power")
    assert msg["error"]["code"] == "expired"
