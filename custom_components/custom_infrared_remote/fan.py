"""Fan learned with the wizard."""

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

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

    Speed buttons stay as button entities: infrared can only step the speed,
    and the fan's speed slider needs an absolute value.
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
        self._attr_supported_features = features
        self._on = None
        self._attr_oscillating = None

    @property
    def is_on(self) -> bool | None:
        """Assumed from what was last sent."""
        return self._on

    async def async_added_to_hass(self) -> None:
        """Restore the assumed state."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state in (STATE_ON, STATE_OFF):
                self._on = last.state == STATE_ON
            self._attr_oscillating = last.attributes.get("oscillating")

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on."""
        await self._send_power(True, self._on)
        self._on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self._send_power(False, self._on)
        self._on = False
        self.async_write_ha_state()

    async def async_oscillate(self, oscillating: bool) -> None:
        """Oscillate is a toggle, so only send it when it changes."""
        if self._attr_oscillating is not oscillating:
            await self._send_role("oscillate")
        self._attr_oscillating = oscillating
        self.async_write_ha_state()
