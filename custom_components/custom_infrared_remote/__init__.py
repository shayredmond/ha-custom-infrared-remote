"""The Custom infrared remote integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import CMD_ID
from .event import listens
from .presses import PressListener
from .templates import button_commands, entry_template, has_main_entity

BASE_PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.EVENT]


def _platforms(entry: ConfigEntry) -> list[Platform]:
    """Return the platforms this remote uses."""
    if (platform := entry_template(entry).platform) is not None:
        return [*BASE_PLATFORMS, platform]
    return BASE_PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a remote from a config entry."""
    _async_remove_deleted_buttons(hass, entry)
    entry.async_on_unload(PressListener(hass, entry).async_start())
    await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when commands or settings change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _platforms(entry))


@callback
def _async_remove_deleted_buttons(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove entities that no longer exist, so none linger unavailable."""
    # The remote entity (unique ID = entry ID) was dropped in 0.3.0; it is not
    # in this set, so installs that had one get it removed here.
    keep = {f"{entry.entry_id}_{command[CMD_ID]}" for command in button_commands(entry)}
    if has_main_entity(entry):
        keep.add(f"{entry.entry_id}_device")
    if listens(entry):
        keep.add(f"{entry.entry_id}_event")
    ent_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if entity.unique_id not in keep:
            ent_reg.async_remove(entity.entity_id)
