"""Event entity: fires when the physical remote sends a learned button."""

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.components.infrared import (
    InfraredReceivedSignal,
    InfraredReceiverConsumerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CMD_NAME,
    CONF_COMMANDS,
    CONF_EMITTER,
    CONF_RECEIVER,
    DOMAIN,
    MIN_TIMINGS,
    REPEAT_WINDOW,
)
from .signal import (
    LearnedSignal,
    async_is_learning,
    async_mark_sent,
    async_recently_sent,
    find_best_match,
    now,
)


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


class LearnedRemoteButtonEvent(InfraredReceiverConsumerEntity, EventEntity):
    """Fires with the button name when the receiver hears a learned button."""

    _attr_has_entity_name = True
    _attr_translation_key = "button_pressed"
    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the event entity."""
        self._entry = entry
        self._commands: list[dict[str, Any]] = list(entry.options[CONF_COMMANDS])
        self._emitter = entry.data[CONF_EMITTER]
        self._infrared_receiver_entity_id = entry.data[CONF_RECEIVER]
        self._attr_unique_id = f"{entry.entry_id}_event"
        self._attr_event_types = [c[CMD_NAME] for c in self._commands]
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._last_name: str | None = None
        self._last_time = 0.0

    async def async_added_to_hass(self) -> None:
        """Also watch the emitter, so sends by other integrations count as echo."""
        await super().async_added_to_hass()

        @callback
        def _emitter_sent(event: Event[EventStateChangedData]) -> None:
            async_mark_sent(self.hass, self._emitter)

        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._emitter], _emitter_sent)
        )

    @callback
    def _handle_signal(self, signal: InfraredReceivedSignal) -> None:
        """Fire the event if the signal is one of the learned buttons."""
        if len(signal.timings) < MIN_TIMINGS:
            return
        if async_recently_sent(self.hass, self._emitter):
            return
        if async_is_learning(self.hass, self._infrared_receiver_entity_id):
            return
        cleaned = LearnedSignal.from_received(signal)
        if (command := find_best_match(cleaned.timings, self._commands)) is None:
            return

        name = command[CMD_NAME]
        moment = now()
        held = name == self._last_name and moment - self._last_time < REPEAT_WINDOW
        # Keep extending the window while the button is held
        self._last_name, self._last_time = name, moment
        if held:
            return

        self._trigger_event(name)
        self.async_write_ha_state()
