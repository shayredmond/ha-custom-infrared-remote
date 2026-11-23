"""Fan learned with the wizard."""

import asyncio
import math
from typing import Any, override

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .const import CONF_SPEED_COUNT, DEFAULT_SPEED_COUNT, STEP_DELAY
from .entity import LearnedDeviceEntity
from .templates import has_main_entity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the fan."""
    if has_main_entity(entry):
        async_add_entities([LearnedFan(entry)])


class LearnedFan(LearnedDeviceEntity, FanEntity, RestoreEntity):
    """A fan controlled with learned buttons.

    With Speed up and Speed down learned, the fan gets a speed slider: setting
    a speed presses them as many times as needed. On, off, speed and
    oscillation also follow presses on the original remote.
    """

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the fan."""
        super().__init__(entry)
        features = FanEntityFeature(0)
        if self._has("power", "power_on"):
            features |= FanEntityFeature.TURN_ON
        if self._has("power", "power_off"):
            features |= FanEntityFeature.TURN_OFF
        if self._has("oscillate"):
            features |= FanEntityFeature.OSCILLATE
        if self._has("speed_up") and self._has("speed_down"):
            features |= FanEntityFeature.SET_SPEED
            self._attr_speed_count = int(
                entry.data.get(CONF_SPEED_COUNT, DEFAULT_SPEED_COUNT)
            )
        self._attr_supported_features = features
        self._on: bool | None = None
        # Speed step from 1 to speed_count, or None until known
        self._step: int | None = None
        self._attr_oscillating = None

    @property
    @override
    def is_on(self) -> bool | None:
        """FanEntity derives this from percentage, which keeps the last speed."""
        return self._on

    @property
    @override
    def percentage(self) -> int | None:
        """Last known speed, kept while the fan is off."""
        if self._step is None:
            return None
        return ranged_value_to_percentage((1, self._attr_speed_count), self._step)

    async def async_added_to_hass(self) -> None:
        """Restore the last known state."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state in (STATE_ON, STATE_OFF):
                self._on = last.state == STATE_ON
            self._attr_oscillating = last.attributes.get("oscillating")
            if (
                self.supported_features & FanEntityFeature.SET_SPEED
                and (percentage := last.attributes.get("percentage")) is not None
            ):
                self._step = self._percentage_to_step(percentage)

    def _percentage_to_step(self, percentage: float) -> int:
        count = self._attr_speed_count
        return max(
            1, min(count, math.ceil(percentage_to_ranged_value((1, count), percentage)))
        )

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on, then set the speed if one was given."""
        await self._send_power(True, self._on)
        self._on = True
        if percentage:
            await self._async_step_to(self._percentage_to_step(percentage))
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self._send_power(False, self._on)
        self._on = False
        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        """Press speed up or down until the fan is at that speed."""
        if percentage == 0:
            await self.async_turn_off()
            return
        if not self._on:
            await self._send_power(True, self._on)
            self._on = True
        await self._async_step_to(self._percentage_to_step(percentage))
        self.async_write_ha_state()

    async def _async_step_to(self, target: int) -> None:
        if self._step is None:
            # Speed unknown: go down to the slowest speed first, which fans
            # stay at however often you press Speed down
            await self._async_press("speed_down", self._attr_speed_count - 1)
            self._step = 1
        if target > self._step:
            await self._async_press("speed_up", target - self._step)
        elif target < self._step:
            await self._async_press("speed_down", self._step - target)
        self._step = target

    async def _async_press(self, role: str, times: int) -> None:
        for index in range(times):
            if index:
                await asyncio.sleep(STEP_DELAY)
            await self._send_role(role)

    async def async_oscillate(self, oscillating: bool) -> None:
        """Oscillate is a toggle, so only send it when it changes."""
        if self._attr_oscillating is not oscillating:
            await self._send_role("oscillate")
        self._attr_oscillating = oscillating
        self.async_write_ha_state()

    @callback
    @override
    def _async_heard(self, role: str) -> bool:
        """Follow the original remote."""
        if role == "power":
            self._on = not self._on
        elif role in ("power_on", "power_off"):
            self._on = role == "power_on"
        elif role == "oscillate":
            self._attr_oscillating = not self._attr_oscillating
        elif role in ("speed_up", "speed_down"):
            if self._step is None or not self._on:
                return False
            change = 1 if role == "speed_up" else -1
            self._step = max(1, min(self._attr_speed_count, self._step + change))
        else:
            return False
        return True
