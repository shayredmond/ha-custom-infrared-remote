"""Shared base for Custom infrared remote entities."""

from typing import Any

from homeassistant.components.infrared import (
    InfraredCommand,
    InfraredEmitterConsumerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import CMD_NAME, CMD_ROLE, CONF_EMITTER, DOMAIN
from .presses import press_signal
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
        )

    async def _send_command(self, command: InfraredCommand) -> None:
        """Send, and tell listeners to ignore the echo."""
        async_mark_sent(self.hass, self._infrared_emitter_entity_id)
        await super()._send_command(command)
        async_mark_sent(self.hass, self._infrared_emitter_entity_id)


class LearnedDeviceEntity(LearnedRemoteEntity):
    """The main entity of a device type: a media player, fan or cover.

    State comes from what Home Assistant sends and from presses on the
    original remote that the receiver hears (see `_async_heard`).
    """

    _attr_name = None

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

    async def async_added_to_hass(self) -> None:
        """Follow presses on the original remote."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, press_signal(self._entry.entry_id), self._async_pressed
            )
        )

    @callback
    def _async_pressed(self, command: dict[str, Any]) -> None:
        if (role := command.get(CMD_ROLE)) in self._roles and self._async_heard(role):
            self.async_write_ha_state()

    @callback
    def _async_heard(self, role: str) -> bool:
        """Update state for a button pressed on the original remote.

        Return True if the state changed.
        """
        return False

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
