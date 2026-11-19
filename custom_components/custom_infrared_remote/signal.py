"""Helpers to describe, clean up and compare learned IR signals."""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from homeassistant.components.infrared import (
    InfraredCommand,
    InfraredReceivedSignal,
    async_subscribe_receiver,
)
from homeassistant.core import HomeAssistant, callback
from infrared_protocols.commands.nec import NECCommand

from .const import (
    CMD_MODULATION,
    CMD_NAME,
    CMD_TIMINGS,
    DEFAULT_MODULATION,
    DOMAIN,
    ECHO_WINDOW,
    LEARN_TIMEOUT,
    MIN_TIMINGS,
)

DATA_LAST_SENT = f"{DOMAIN}_last_sent"

# One NEC frame: leader pair + 32 bit pairs + end pulse
NEC_FRAME_LENGTH = 67


class LearnedCommand(InfraredCommand):
    """IR command that replays raw timings captured from a remote."""

    def __init__(self, timings: list[int], modulation: int) -> None:
        """Initialize the command."""
        super().__init__(modulation=modulation)
        self._timings = timings

    def get_raw_timings(self) -> list[int]:
        """Return the captured timings."""
        return self._timings

    @classmethod
    def from_stored(cls, stored: dict[str, Any]) -> LearnedCommand:
        """Build a command from what is stored in the config entry."""
        return cls(stored[CMD_TIMINGS], stored[CMD_MODULATION])


@dataclass(slots=True)
class LearnedSignal:
    """A captured signal after clean-up."""

    timings: list[int]
    modulation: int
    carrier_reported: bool
    protocol: str | None = None
    held_repeats: int = 0

    @classmethod
    def from_received(cls, signal: InfraredReceivedSignal) -> LearnedSignal:
        """Clean up a received signal.

        If the button was held, NEC remotes send repeat codes after the frame.
        Those are dropped so a button press sends the command once.
        """
        timings = list(signal.timings)
        protocol = None
        held_repeats = 0
        if nec := NECCommand.from_raw_timings(timings):
            low, high = nec.address & 0xFF, nec.address >> 8
            # Standard NEC repeats the address inverted; show it as 8 bits
            address = f"0x{low:02X}" if low ^ high == 0xFF else f"0x{nec.address:04X}"
            protocol = f"NEC, address {address}, command 0x{nec.command:02X}"
            if nec.repeat_count:
                held_repeats = nec.repeat_count
                timings = timings[:NEC_FRAME_LENGTH]
        return cls(
            timings=timings,
            modulation=signal.modulation or DEFAULT_MODULATION,
            carrier_reported=signal.modulation is not None,
            protocol=protocol,
            held_repeats=held_repeats,
        )

    def as_stored(self, name: str) -> dict[str, Any]:
        """Return what gets stored for a command."""
        return {
            CMD_NAME: name,
            CMD_TIMINGS: self.timings,
            CMD_MODULATION: self.modulation,
        }

    def summary(self) -> str:
        """Return a one-line, human readable summary."""
        duration_ms = sum(abs(t) for t in self.timings) / 1000
        carrier = f"{self.modulation / 1000:g} kHz"
        if not self.carrier_reported:
            carrier += " (assumed)"
        parts = [
            self.protocol or "Unknown protocol, stored as raw timings",
            f"{len(self.timings)} pulses",
            f"{duration_ms:.0f} ms",
            carrier,
        ]
        return " · ".join(parts)


def signal_distance(a: list[int], b: list[int]) -> float | None:
    """Return how far apart two signals are, or None if they don't match.

    0 is identical. NEC codes compare by address and command, so they are
    either 0 or None. Raw codes compare timing by timing and return the mean
    relative difference.
    """
    nec_a = NECCommand.from_raw_timings(a)
    nec_b = NECCommand.from_raw_timings(b)
    if nec_a and nec_b:
        same = (nec_a.address, nec_a.command) == (nec_b.address, nec_b.command)
        return 0.0 if same else None
    if abs(len(a) - len(b)) > 2:
        return None
    total = 0.0
    pairs = 0
    for x, y in zip(a, b, strict=False):
        if (x > 0) != (y > 0):
            return None
        diff = abs(abs(x) - abs(y))
        if diff > max(200, 0.25 * abs(x)):
            return None
        total += diff / max(abs(x), 1)
        pairs += 1
    return total / pairs if pairs else None


def signals_match(a: list[int], b: list[int]) -> bool:
    """Return True if two timing lists are very likely the same button."""
    return signal_distance(a, b) is not None


def find_best_match(
    timings: list[int], commands: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the stored command closest to the timings, or None."""
    best: dict[str, Any] | None = None
    best_distance = float("inf")
    for command in commands:
        distance = signal_distance(timings, command[CMD_TIMINGS])
        if distance is not None and distance < best_distance:
            best, best_distance = command, distance
    return best


def find_duplicate(signal: LearnedSignal, commands: list[dict[str, Any]]) -> str | None:
    """Return the name of a stored command that matches the signal."""
    if match := find_best_match(signal.timings, commands):
        return match[CMD_NAME]
    return None


def now() -> float:
    """Monotonic clock, patched in tests."""
    return time.monotonic()


@callback
def async_mark_sent(hass: HomeAssistant, emitter_entity_id: str) -> None:
    """Remember that something was just sent through this emitter."""
    hass.data.setdefault(DATA_LAST_SENT, {})[emitter_entity_id] = now()


@callback
def async_recently_sent(hass: HomeAssistant, emitter_entity_id: str) -> bool:
    """Return True if this emitter sent something within the echo window."""
    sent = hass.data.get(DATA_LAST_SENT, {}).get(emitter_entity_id)
    return sent is not None and now() - sent < ECHO_WINDOW


async def async_learn_signal(
    hass: HomeAssistant, receiver_entity_id: str, timeout: float = LEARN_TIMEOUT
) -> LearnedSignal | None:
    """Return the first real signal the receiver gets, or None on timeout."""
    future: asyncio.Future[InfraredReceivedSignal] = hass.loop.create_future()

    @callback
    def _async_on_signal(signal: InfraredReceivedSignal) -> None:
        if len(signal.timings) < MIN_TIMINGS:
            return
        if not future.done():
            future.set_result(signal)

    unsubscribe = async_subscribe_receiver(hass, receiver_entity_id, _async_on_signal)
    try:
        async with asyncio.timeout(timeout):
            return LearnedSignal.from_received(await future)
    except TimeoutError:
        return None
    finally:
        unsubscribe()
