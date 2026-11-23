"""Event entity: fires when the physical remote sends a learned button."""

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.components.infrared.helpers import InfraredConsumerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CMD_NAME, CONF_COMMANDS, CONF_RECEIVER, DOMAIN
from .presses import press_signal


def listens(entry: ConfigEntry) -> bool:
    """Return True if this remote has buttons to listen for.

    To stop listening, disable the event entity like any other entity.
    """
    return bool(entry.options.get(CONF_COMMANDS))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the event entity when there are buttons."""
    if listens(entry):
        async_add_entities([LearnedRemoteButtonEvent(entry)])


class LearnedRemoteButtonEvent(InfraredConsumerEntity, EventEntity):
    """Fires with the button name when the receiver hears a learned button."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "button_pressed"
    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the event entity."""
        self._entry = entry
        commands: list[dict[str, Any]] = list(entry.options[CONF_COMMANDS])
        self._receiver = entry.data[CONF_RECEIVER]
        self._attr_unique_id = f"{entry.entry_id}_event"
        self._attr_event_types = [c[CMD_NAME] for c in commands]
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        """Follow the receiver's availability and listen for presses."""
        await super().async_added_to_hass()
        self.async_on_remove(self._async_track_availability(self._receiver))
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, press_signal(self._entry.entry_id), self._async_pressed
            )
        )

    @callback
    def _async_pressed(self, command: dict[str, Any]) -> None:
        self._trigger_event(command[CMD_NAME])
        self.async_write_ha_state()
