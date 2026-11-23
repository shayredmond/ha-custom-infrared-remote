"""Test the device types: media player, fan and cover."""

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
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
from custom_components.custom_infrared_remote.templates import get_template

from .conftest import nec

POWER = nec(0x08)
VOL_UP = nec(0x02)
MUTE = nec(0x09)
HDMI_1 = nec(0x20)


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
