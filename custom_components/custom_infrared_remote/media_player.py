"""Media player for TVs, projectors and speakers learned with the wizard."""

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import LearnedDeviceEntity
from .templates import has_main_entity

PARALLEL_UPDATES = 1

SOURCE_PREFIX = "source_"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the media player."""
    if has_main_entity(entry):
        async_add_entities([LearnedMediaPlayer(entry)])


class LearnedMediaPlayer(LearnedDeviceEntity, MediaPlayerEntity, RestoreEntity):
    """A TV, projector or speaker controlled with learned buttons."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the media player."""
        super().__init__(entry)
        features = MediaPlayerEntityFeature(0)
        if self._has("power", "power_on"):
            features |= MediaPlayerEntityFeature.TURN_ON
        if self._has("power", "power_off"):
            features |= MediaPlayerEntityFeature.TURN_OFF
        if self._has("volume_up", "volume_down"):
            features |= MediaPlayerEntityFeature.VOLUME_STEP
        if self._has("mute"):
            features |= MediaPlayerEntityFeature.VOLUME_MUTE
        if self._has("play", "play_pause"):
            features |= MediaPlayerEntityFeature.PLAY
        if self._has("pause", "play_pause"):
            features |= MediaPlayerEntityFeature.PAUSE
        if self._has("stop"):
            features |= MediaPlayerEntityFeature.STOP
        if self._has("next"):
            features |= MediaPlayerEntityFeature.NEXT_TRACK
        if self._has("previous"):
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        self._sources = {
            self._role_names[role]: role
            for role in self._roles
            if role.startswith(SOURCE_PREFIX)
        }
        if self._sources:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
            self._attr_source_list = list(self._sources)
        self._attr_supported_features = features
        self._attr_state = None

    async def async_added_to_hass(self) -> None:
        """Restore the assumed state."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state in (MediaPlayerState.ON, MediaPlayerState.OFF):
                self._attr_state = MediaPlayerState(last.state)
            self._attr_source = last.attributes.get("source")

    def _is_on(self) -> bool | None:
        if self._attr_state is None:
            return None
        return self._attr_state != MediaPlayerState.OFF

    async def async_turn_on(self) -> None:
        """Turn on."""
        await self._send_power(True, self._is_on())
        self._attr_state = MediaPlayerState.ON
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn off."""
        await self._send_power(False, self._is_on())
        self._attr_state = MediaPlayerState.OFF
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        """Volume up."""
        await self._send_role("volume_up")

    async def async_volume_down(self) -> None:
        """Volume down."""
        await self._send_role("volume_down")

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute is a toggle on almost every remote."""
        await self._send_role("mute")

    async def async_media_play(self) -> None:
        """Play."""
        await self._send_role("play" if self._has("play") else "play_pause")

    async def async_media_pause(self) -> None:
        """Pause."""
        await self._send_role("pause" if self._has("pause") else "play_pause")

    async def async_media_play_pause(self) -> None:
        """Play or pause."""
        if self._has("play_pause"):
            await self._send_role("play_pause")
        elif self._has("play"):
            await self._send_role("play")

    async def async_media_stop(self) -> None:
        """Stop."""
        await self._send_role("stop")

    async def async_media_next_track(self) -> None:
        """Next."""
        await self._send_role("next")

    async def async_media_previous_track(self) -> None:
        """Previous."""
        await self._send_role("previous")

    async def async_select_source(self, source: str) -> None:
        """Switch input."""
        await self._send_role(self._sources[source])
        self._attr_source = source
        self.async_write_ha_state()
