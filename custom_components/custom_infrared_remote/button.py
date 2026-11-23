"""One button per learned command."""

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CMD_ID, CMD_NAME
from .entity import LearnedRemoteEntity
from .signal import LearnedCommand
from .templates import button_commands

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a button for each command the main entity doesn't cover."""
    async_add_entities(
        LearnedCommandButton(entry, command) for command in button_commands(entry)
    )


class LearnedCommandButton(LearnedRemoteEntity, ButtonEntity):
    """Button that sends one learned command."""

    def __init__(self, entry: ConfigEntry, command: dict[str, Any]) -> None:
        """Initialize the button."""
        super().__init__(entry)
        self._attr_name = command[CMD_NAME]
        self._attr_unique_id = f"{entry.entry_id}_{command[CMD_ID]}"
        self._command = LearnedCommand.from_stored(command)

    async def async_press(self) -> None:
        """Send the command."""
        await self._send_command(self._command)
