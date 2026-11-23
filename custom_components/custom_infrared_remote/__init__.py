"""The Custom infrared remote integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import CMD_ID, DOMAIN
from .event import listens
from .panel import async_setup_panel
from .templates import button_commands, entry_template, has_main_entity

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

BASE_PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.EVENT]


def _platforms(entry: ConfigEntry) -> list[Platform]:
    """Return the platforms this remote uses."""
    if (platform := entry_template(entry).platform) is not None:
        return [*BASE_PLATFORMS, platform]
    return BASE_PLATFORMS


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the learning screen."""
    await async_setup_panel(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a remote from a config entry."""
    # Create the device now, so it exists (and links to the learning screen)
    # before any button is learned
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        model="Custom infrared remote",
        configuration_url=f"homeassistant://custom-infrared-remote/{entry.entry_id}",
    )
    _async_remove_deleted_buttons(hass, entry)
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
