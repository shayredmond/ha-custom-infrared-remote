"""The Learned IR remote integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import CMD_ID, CONF_COMMANDS

PLATFORMS: list[Platform] = [Platform.REMOTE, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a remote from a config entry."""
    _async_remove_deleted_buttons(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when commands or settings change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


@callback
def _async_remove_deleted_buttons(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove entities of commands that were deleted, so none linger unavailable."""
    keep = {entry.entry_id} | {
        f"{entry.entry_id}_{command[CMD_ID]}"
        for command in entry.options.get(CONF_COMMANDS, [])
    }
    ent_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if entity.unique_id not in keep:
            ent_reg.async_remove(entity.entity_id)
