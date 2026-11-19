"""Remote entity: send, learn and delete commands by name."""

import asyncio
from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from homeassistant.components import persistent_notification
from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    ATTR_TIMEOUT,
    DEFAULT_DELAY_SECS,
    RemoteEntity,
    RemoteEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CMD_ID,
    CMD_NAME,
    CONF_COMMANDS,
    CONF_RECEIVER,
    DOMAIN,
    LEARN_TIMEOUT,
)
from .entity import LearnedRemoteEntity
from .signal import LearnedCommand, async_learn_signal

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the remote entity."""
    async_add_entities([LearnedRemote(entry)])


class LearnedRemote(LearnedRemoteEntity, RemoteEntity):
    """The remote itself. Its commands are the learned buttons."""

    _attr_name = None
    _attr_supported_features = (
        RemoteEntityFeature.LEARN_COMMAND | RemoteEntityFeature.DELETE_COMMAND
    )
    # IR is one-way, so the remote cannot know if the device is on
    _attr_is_on = None
    _attr_assumed_state = True
    # Hidden by default: its on/off controls mean nothing for a learned remote.
    # The buttons are the controls; the remote is for send_command in automations.
    _attr_entity_registry_visible_default = False

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the remote."""
        super().__init__(entry)
        self._attr_unique_id = entry.entry_id

    @property
    def _commands(self) -> list[dict[str, Any]]:
        return list(self._entry.options.get(CONF_COMMANDS, []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """List the commands so they are easy to find in automations."""
        return {"commands": [c[CMD_NAME] for c in self._commands]}

    def _find(self, name: str) -> dict[str, Any]:
        for command in self._commands:
            if command[CMD_NAME].casefold() == name.casefold():
                return command
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_command",
            translation_placeholders={
                "command": name,
                "commands": ", ".join(c[CMD_NAME] for c in self._commands),
            },
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Explain that on and off are not supported."""
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="on_off_not_supported"
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Explain that on and off are not supported."""
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="on_off_not_supported"
        )

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send one or more commands by name."""
        # Resolve every name first, so a typo sends nothing
        resolved = [LearnedCommand.from_stored(self._find(name)) for name in command]
        repeats = kwargs.get(ATTR_NUM_REPEATS, 1)
        delay = kwargs.get(ATTR_DELAY_SECS, DEFAULT_DELAY_SECS)

        first = True
        for _ in range(repeats):
            for ir_command in resolved:
                if not first:
                    await asyncio.sleep(delay)
                first = False
                await self._send_command(ir_command)

    async def async_learn_command(self, **kwargs: Any) -> None:
        """Learn commands by name with remote.learn_command."""
        names: list[str] = list(kwargs.get("command") or [])
        if not names:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_command_name"
            )
        timeout = kwargs.get(ATTR_TIMEOUT) or LEARN_TIMEOUT
        receiver = self._entry.data[CONF_RECEIVER]
        commands = self._commands
        notification_id = f"{DOMAIN}_{self._entry.entry_id}_learn"

        try:
            for name in names:
                persistent_notification.async_create(
                    self.hass,
                    f"Point your remote at the receiver and press **{name}**.",
                    title=f"Learning {self._entry.title}",
                    notification_id=notification_id,
                )
                signal = await async_learn_signal(self.hass, receiver, timeout)
                if signal is None:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="no_signal",
                        translation_placeholders={"command": name},
                    )
                stored = signal.as_stored(name)
                existing = next(
                    (c for c in commands if c[CMD_NAME].casefold() == name.casefold()),
                    None,
                )
                if existing:
                    commands = [
                        {**c, **stored, CMD_NAME: c[CMD_NAME]} if c is existing else c
                        for c in commands
                    ]
                else:
                    commands.append({CMD_ID: uuid4().hex, **stored})
        finally:
            persistent_notification.async_dismiss(self.hass, notification_id)
            # Keep what was learned, even if a later command timed out
            if commands != self._commands:
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    options={**self._entry.options, CONF_COMMANDS: commands},
                )

    async def async_delete_command(self, **kwargs: Any) -> None:
        """Delete commands by name with remote.delete_command."""
        remove = {self._find(name)[CMD_ID] for name in kwargs.get("command") or []}
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={
                **self._entry.options,
                CONF_COMMANDS: [c for c in self._commands if c[CMD_ID] not in remove],
            },
        )
