"""Device types the setup wizard offers, and the buttons each one asks for.

A device type turns a set of learned buttons into a proper Home Assistant
entity (media player, fan or cover), so the remote shows up like a real
device on dashboards. Buttons the entity can't express become button
entities, and "Something else" keeps the plain list of buttons.
"""

from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

from .const import CMD_ROLE, CONF_COMMANDS, CONF_DEVICE_TYPE

DEVICE_TV = "tv"
DEVICE_PROJECTOR = "projector"
DEVICE_SPEAKER = "speaker"
DEVICE_FAN = "fan"
DEVICE_BLINDS = "blinds"
DEVICE_SCREEN = "screen"
DEVICE_GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class Role:
    """A button the wizard asks for."""

    key: str
    name: str
    # Ticked by default in the button list
    default: bool = False
    # Section of the button list it appears in
    group: str = "controls"


@dataclass(frozen=True, slots=True)
class DeviceTemplate:
    """A device type in the wizard."""

    key: str
    # Name suggested for the device
    suggested_name: str
    platform: Platform | None
    device_class: str | None
    roles: tuple[Role, ...] = ()
    # Roles the main entity uses. Other learned roles become buttons.
    mapped: frozenset[str] = field(default_factory=frozenset)

    def role(self, key: str) -> Role | None:
        """Return the role with this key."""
        return next((r for r in self.roles if r.key == key), None)


def _grouped(group: str, *roles: Role) -> tuple[Role, ...]:
    return tuple(Role(r.key, r.name, r.default, group) for r in roles)


POWER = _grouped(
    "power",
    Role("power", "Power", default=True),
    Role("power_on", "Power on"),
    Role("power_off", "Power off"),
)
VOLUME = _grouped(
    "volume",
    Role("volume_up", "Volume up", default=True),
    Role("volume_down", "Volume down", default=True),
    Role("mute", "Mute", default=True),
)
PLAYBACK = _grouped(
    "playback",
    Role("play_pause", "Play/pause"),
    Role("play", "Play"),
    Role("pause", "Pause"),
    Role("stop", "Stop"),
    Role("next", "Next"),
    Role("previous", "Previous"),
)
INPUTS = _grouped(
    "inputs",
    Role("input", "Input"),
    Role("source_hdmi_1", "HDMI 1"),
    Role("source_hdmi_2", "HDMI 2"),
    Role("source_hdmi_3", "HDMI 3"),
    Role("source_hdmi_4", "HDMI 4"),
)
NAVIGATION = _grouped(
    "navigation",
    Role("home", "Home"),
    Role("back", "Back"),
    Role("up", "Up"),
    Role("down", "Down"),
    Role("left", "Left"),
    Role("right", "Right"),
    Role("ok", "OK"),
)
CHANNELS = _grouped(
    "channels",
    Role("channel_up", "Channel up"),
    Role("channel_down", "Channel down"),
)

MEDIA_MAPPED = frozenset(
    {
        "power",
        "power_on",
        "power_off",
        "volume_up",
        "volume_down",
        "mute",
        "play_pause",
        "play",
        "pause",
        "stop",
        "next",
        "previous",
        "source_hdmi_1",
        "source_hdmi_2",
        "source_hdmi_3",
        "source_hdmi_4",
    }
)


def _with_defaults(roles: tuple[Role, ...], defaults: set[str]) -> tuple[Role, ...]:
    """Return roles with their default ticks replaced."""
    return tuple(Role(r.key, r.name, r.key in defaults, r.group) for r in roles)


TEMPLATES: dict[str, DeviceTemplate] = {
    DEVICE_TV: DeviceTemplate(
        key=DEVICE_TV,
        suggested_name="TV",
        platform=Platform.MEDIA_PLAYER,
        device_class="tv",
        roles=POWER + VOLUME + CHANNELS + INPUTS + PLAYBACK + NAVIGATION,
        mapped=MEDIA_MAPPED,
    ),
    DEVICE_PROJECTOR: DeviceTemplate(
        key=DEVICE_PROJECTOR,
        suggested_name="Projector",
        platform=Platform.MEDIA_PLAYER,
        device_class="projector",
        roles=_with_defaults(POWER + INPUTS + VOLUME + NAVIGATION, {"power", "input"}),
        mapped=MEDIA_MAPPED,
    ),
    DEVICE_SPEAKER: DeviceTemplate(
        key=DEVICE_SPEAKER,
        suggested_name="Speakers",
        platform=Platform.MEDIA_PLAYER,
        device_class="receiver",
        roles=POWER + VOLUME + INPUTS + PLAYBACK,
        mapped=MEDIA_MAPPED,
    ),
    DEVICE_FAN: DeviceTemplate(
        key=DEVICE_FAN,
        suggested_name="Fan",
        platform=Platform.FAN,
        device_class=None,
        roles=POWER
        + (
            Role("speed_up", "Speed up", default=True),
            Role("speed_down", "Speed down", default=True),
            Role("oscillate", "Oscillate", default=True),
            Role("mode", "Mode"),
            Role("timer", "Timer"),
        ),
        mapped=frozenset({"power", "power_on", "power_off", "oscillate"}),
    ),
    DEVICE_BLINDS: DeviceTemplate(
        key=DEVICE_BLINDS,
        suggested_name="Blinds",
        platform=Platform.COVER,
        device_class="blind",
        roles=(
            Role("open", "Open", default=True),
            Role("close", "Close", default=True),
            Role("stop", "Stop", default=True),
        ),
        mapped=frozenset({"open", "close", "stop"}),
    ),
    DEVICE_SCREEN: DeviceTemplate(
        key=DEVICE_SCREEN,
        suggested_name="Projector screen",
        platform=Platform.COVER,
        device_class="shade",
        roles=(
            Role("open", "Up", default=True),
            Role("close", "Down", default=True),
            Role("stop", "Stop", default=True),
        ),
        mapped=frozenset({"open", "close", "stop"}),
    ),
    DEVICE_GENERIC: DeviceTemplate(
        key=DEVICE_GENERIC,
        suggested_name="",
        platform=None,
        device_class=None,
    ),
}


def get_template(device_type: str | None) -> DeviceTemplate:
    """Return the template, falling back to the plain list of buttons."""
    return TEMPLATES.get(device_type or DEVICE_GENERIC, TEMPLATES[DEVICE_GENERIC])


def entry_template(entry: ConfigEntry) -> DeviceTemplate:
    """Return the template a config entry was set up with."""
    return get_template(entry.data.get(CONF_DEVICE_TYPE))


def role_commands(entry: ConfigEntry) -> dict[str, dict[str, Any]]:
    """Return the learned commands that fill a role of the main entity."""
    template = entry_template(entry)
    return {
        c[CMD_ROLE]: c
        for c in entry.options.get(CONF_COMMANDS, [])
        if c.get(CMD_ROLE) in template.mapped
    }


def button_commands(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Return the learned commands that become button entities."""
    template = entry_template(entry)
    return [
        c
        for c in entry.options.get(CONF_COMMANDS, [])
        if c.get(CMD_ROLE) not in template.mapped
    ]


def has_main_entity(entry: ConfigEntry) -> bool:
    """Return True if the entry gets a media player, fan or cover."""
    return entry_template(entry).platform is not None and bool(role_commands(entry))
