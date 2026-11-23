"""Shared base for Custom infrared remote entities."""

from homeassistant.components.infrared import (
    InfraredCommand,
    InfraredEmitterConsumerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CMD_NAME, CONF_EMITTER, DOMAIN
from .signal import LearnedCommand, async_mark_sent
from .templates import entry_template, role_commands


class LearnedRemoteEntity(InfraredEmitterConsumerEntity):
    """Entity that belongs to one remote device and sends through its emitter."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        self._entry = entry
        self._infrared_emitter_entity_id = entry.data[CONF_EMITTER]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            model="Custom infrared remote",
            # Opens the learning screen from the device page
            configuration_url=f"homeassistant://custom-infrared-remote/{entry.entry_id}",
        )

    async def _send_command(self, command: InfraredCommand) -> None:
        """Send, and tell listeners to ignore the echo."""
        async_mark_sent(self.hass, self._infrared_emitter_entity_id)
        await super()._send_command(command)
        async_mark_sent(self.hass, self._infrared_emitter_entity_id)


class LearnedDeviceEntity(LearnedRemoteEntity):
    """The main entity of a device type: a media player, fan or cover.

    Infrared only goes one way, so state is assumed from what was sent.
    """

    _attr_name = None
    _attr_assumed_state = True

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry)
        template = entry_template(entry)
        self._attr_unique_id = f"{entry.entry_id}_device"
        self._attr_device_class = template.device_class
        self._roles = {
            role: LearnedCommand.from_stored(command)
            for role, command in role_commands(entry).items()
        }
        self._role_names = {
            role: command[CMD_NAME] for role, command in role_commands(entry).items()
        }

    def _has(self, *roles: str) -> bool:
        return any(role in self._roles for role in roles)

    async def _send_role(self, role: str) -> None:
        await self._send_command(self._roles[role])

    async def _send_power(self, on: bool, currently_on: bool | None) -> None:
        """Send discrete power on/off if learned, else toggle when needed."""
        discrete = "power_on" if on else "power_off"
        if self._has(discrete):
            await self._send_role(discrete)
        elif self._has("power") and currently_on is not on:
            await self._send_role("power")
