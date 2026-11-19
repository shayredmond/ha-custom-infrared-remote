"""Shared base for Custom infrared remote entities."""

from homeassistant.components.infrared import (
    InfraredCommand,
    InfraredEmitterConsumerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_EMITTER, DOMAIN
from .signal import async_mark_sent


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
