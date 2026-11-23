"""Hear the original remote: one listener per remote, shared by its entities.

The receiver tells us when someone uses the physical remote. The event entity
fires on it, and the main entity (fan, media player) updates its state from
it, so Home Assistant stays right when the remote is used instead of the app.
"""

import logging
from typing import Any

from homeassistant.components.infrared import (
    InfraredReceivedSignal,
    async_subscribe_receiver,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
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

_LOGGER = logging.getLogger(__name__)


def press_signal(entry_id: str) -> str:
    """Dispatcher signal sent with the command when a learned button is heard."""
    return f"{DOMAIN}_{entry_id}_pressed"


class PressListener:
    """Subscribe to the receiver while it is available and report presses.

    Ignores noise, our own transmissions (echo), presses made to teach a
    remote, and the repeats a held button sends.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the listener."""
        self.hass = hass
        self._entry_id = entry.entry_id
        self._commands: list[dict[str, Any]] = list(
            entry.options.get(CONF_COMMANDS, [])
        )
        self._emitter = entry.data[CONF_EMITTER]
        self._receiver = entry.data[CONF_RECEIVER]
        self._unsubscribe: CALLBACK_TYPE | None = None
        self._last_name: str | None = None
        self._last_time = 0.0

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Start listening. Returns a callback that stops."""

        @callback
        def _receiver_changed(event: Event[EventStateChangedData]) -> None:
            self._async_update()

        @callback
        def _emitter_sent(event: Event[EventStateChangedData]) -> None:
            # Sends by other integrations through the same emitter are echo too
            async_mark_sent(self.hass, self._emitter)

        remove_receiver = async_track_state_change_event(
            self.hass, [self._receiver], _receiver_changed
        )
        remove_emitter = async_track_state_change_event(
            self.hass, [self._emitter], _emitter_sent
        )
        self._async_update()

        @callback
        def _stop() -> None:
            remove_receiver()
            remove_emitter()
            self._async_unsubscribe()

        return _stop

    @callback
    def _async_update(self) -> None:
        state = self.hass.states.get(self._receiver)
        if state is None or state.state == STATE_UNAVAILABLE:
            self._async_unsubscribe()
            return
        if self._unsubscribe is not None:
            return
        try:
            self._unsubscribe = async_subscribe_receiver(
                self.hass, self._receiver, self._async_on_signal
            )
        except HomeAssistantError as err:
            _LOGGER.debug("Can't listen to %s yet: %s", self._receiver, err)

    @callback
    def _async_unsubscribe(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    @callback
    def _async_on_signal(self, signal: InfraredReceivedSignal) -> None:
        if len(signal.timings) < MIN_TIMINGS:
            return
        if async_recently_sent(self.hass, self._emitter):
            return
        if async_is_learning(self.hass, self._receiver):
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
        async_dispatcher_send(self.hass, press_signal(self._entry_id), command)
