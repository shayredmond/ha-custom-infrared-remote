"""Test the event entity that fires when the original remote is used."""

from unittest.mock import patch

import pytest
from homeassistant.components.infrared import InfraredReceivedSignal
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.infrared.common import (
    MockInfraredEmitterEntity,
    MockInfraredReceiverEntity,
)

from custom_components.custom_infrared_remote.signal import (
    LearnedCommand,
    find_best_match,
)

from .conftest import POWER, RAW, VOL_UP, nec

EVENT = "event.living_room_tv_remote_button"


class Clock:
    """Controllable monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    """Patch the integration's clock."""
    clock = Clock()
    with (
        patch("custom_components.custom_infrared_remote.signal.now", clock),
        patch("custom_components.custom_infrared_remote.presses.now", clock),
    ):
        yield clock


@pytest.fixture
async def setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    clock: Clock,
) -> MockConfigEntry:
    """Set up the remote with Power and Volume up learned."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


def _hear(receiver: MockInfraredReceiverEntity, timings: list[int]) -> None:
    receiver._handle_received_signal(InfraredReceivedSignal(timings))


async def test_fires_on_learned_button(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    clock: Clock,
) -> None:
    """Pressing a learned button on the original remote fires the event."""
    state = hass.states.get(EVENT)
    assert state.state == STATE_UNKNOWN
    assert state.attributes["event_types"] == ["Power", "Volume up"]

    _hear(mock_infrared_receiver_entity, VOL_UP)
    await hass.async_block_till_done()
    state = hass.states.get(EVENT)
    assert state.attributes["event_type"] == "Volume up"
    first = state.state

    # A different button right after still fires
    clock.now += 0.1
    _hear(mock_infrared_receiver_entity, POWER)
    await hass.async_block_till_done()
    state = hass.states.get(EVENT)
    assert state.attributes["event_type"] == "Power"
    assert state.state != first


async def test_ignores_unknown_and_noise(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Buttons that were not learned, and noise, fire nothing."""
    _hear(mock_infrared_receiver_entity, nec(0x55))
    _hear(mock_infrared_receiver_entity, RAW)
    _hear(mock_infrared_receiver_entity, [500, -500])
    await hass.async_block_till_done()
    assert hass.states.get(EVENT).state == STATE_UNKNOWN


async def test_held_button_fires_once(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    clock: Clock,
) -> None:
    """Full frames repeated while a button is held count as one press."""
    fired: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda e: e.data["entity_id"] == EVENT and fired.append(e.data["new_state"]),
    )
    for _ in range(5):
        _hear(mock_infrared_receiver_entity, POWER)
        clock.now += 0.11
    await hass.async_block_till_done()
    assert len(fired) == 1

    # Released, then pressed again
    clock.now += 1
    _hear(mock_infrared_receiver_entity, POWER)
    await hass.async_block_till_done()
    assert len(fired) == 2


async def test_ignores_own_echo(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    clock: Clock,
) -> None:
    """The receiver hearing our own send does not fire the event."""
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.living_room_tv_power"},
        blocking=True,
    )
    _hear(mock_infrared_receiver_entity, POWER)
    await hass.async_block_till_done()
    assert hass.states.get(EVENT).state == STATE_UNKNOWN

    clock.now += 1
    _hear(mock_infrared_receiver_entity, POWER)
    await hass.async_block_till_done()
    assert hass.states.get(EVENT).attributes["event_type"] == "Power"


async def test_ignores_echo_from_other_integrations(
    hass: HomeAssistant,
    setup: MockConfigEntry,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    clock: Clock,
) -> None:
    """Sends through the same emitter by anything else also count as echo."""
    # Straight to the emitter, the way another integration would send
    await mock_infrared_emitter_entity.async_send_command_internal(
        LearnedCommand(POWER, 38000)
    )
    await hass.async_block_till_done()
    _hear(mock_infrared_receiver_entity, POWER)
    await hass.async_block_till_done()
    assert hass.states.get(EVENT).state == STATE_UNKNOWN


async def test_closest_match_wins() -> None:
    """When two raw buttons both match, the closer one is picked."""
    base = [3000, -1500, 500, -500, 500, -1500, 500, -500, 500, -10000]
    near = [3050, -1480, 510, -520, 490, -1520, 500, -500, 510, -10000]
    far = [3300, -1650, 560, -560, 560, -1650, 560, -560, 560, -10000]
    commands = [
        {"name": "Far", "timings": far},
        {"name": "Near", "timings": near},
    ]
    assert find_best_match(base, commands)["name"] == "Near"


async def test_old_listen_off_is_ignored(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
) -> None:
    """Entries saved with the old listen setting off still get the event entity."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, "listen": False}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(EVENT)


async def test_settings_drops_old_listen(
    hass: HomeAssistant, setup: MockConfigEntry
) -> None:
    """Saving settings removes the old listen key and has no listen field."""
    hass.config_entries.async_update_entry(setup, data={**setup.data, "listen": False})
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(setup.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    assert [str(k) for k in result["data_schema"].schema] == [
        "emitter_entity_id",
        "receiver_entity_id",
    ]
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "emitter_entity_id": setup.data["emitter_entity_id"],
            "receiver_entity_id": setup.data["receiver_entity_id"],
        },
    )
    await hass.async_block_till_done()
    assert "listen" not in setup.data
    assert hass.states.get(EVENT)
