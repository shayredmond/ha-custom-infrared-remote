"""Blinds, curtains and projector screens learned with the wizard."""

from typing import Any

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import LearnedDeviceEntity
from .templates import has_main_entity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the cover."""
    if has_main_entity(entry):
        async_add_entities([LearnedCover(entry)])


class LearnedCover(LearnedDeviceEntity, CoverEntity):
    """A cover controlled with learned buttons.

    Its position is unknown, so open, close and stop always stay available.
    """

    _attr_is_closed = None

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the cover."""
        super().__init__(entry)
        features = CoverEntityFeature(0)
        if self._has("open"):
            features |= CoverEntityFeature.OPEN
        if self._has("close"):
            features |= CoverEntityFeature.CLOSE
        if self._has("stop"):
            features |= CoverEntityFeature.STOP
        self._attr_supported_features = features

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open."""
        await self._send_role("open")

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close."""
        await self._send_role("close")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop."""
        await self._send_role("stop")
