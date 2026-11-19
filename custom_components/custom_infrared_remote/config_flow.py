"""Config and options flows for the Custom infrared remote integration.

One config entry is one remote. Commands live in the entry options, so the
options flow is where they are learned, re-learned, renamed and deleted.
"""

import asyncio
from typing import Any, override
from uuid import uuid4

import probatio
from homeassistant.components.infrared import (
    DOMAIN as INFRARED_DOMAIN,
)
from homeassistant.components.infrared import (
    async_get_emitters,
    async_get_receivers,
    async_send_command,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CMD_ID,
    CMD_MODULATION,
    CMD_NAME,
    CMD_TIMINGS,
    CONF_COMMANDS,
    CONF_EMITTER,
    CONF_LISTEN,
    CONF_RECEIVER,
    DOMAIN,
)
from .signal import (
    LearnedCommand,
    LearnedSignal,
    async_learn_signal,
    async_mark_sent,
    find_duplicate,
)

CONF_COMMAND = "command"


def _emitter_selector(hass: HomeAssistant) -> EntitySelector:
    return EntitySelector(
        EntitySelectorConfig(
            domain=INFRARED_DOMAIN, include_entities=async_get_emitters(hass)
        )
    )


def _receiver_selector(hass: HomeAssistant) -> EntitySelector:
    return EntitySelector(
        EntitySelectorConfig(
            domain=INFRARED_DOMAIN, include_entities=async_get_receivers(hass)
        )
    )


def _command_options(commands: list[dict[str, Any]]) -> list[SelectOptionDict]:
    return [
        SelectOptionDict(value=command[CMD_ID], label=command[CMD_NAME])
        for command in commands
    ]


class LearnLoopMixin:
    """Steps shared by the config flow and the options flow.

    command_name -> learn (progress) -> learn_done -> review (menu)
    review offers: test, save and learn the next one, save and finish, retry.
    """

    hass: HomeAssistant

    _remote_name: str
    _emitter: str
    _receiver: str
    _commands: list[dict[str, Any]]

    _pending_name: str | None = None
    _replace_id: str | None = None
    _signal: LearnedSignal | None = None
    _learn_task: asyncio.Task[LearnedSignal | None] | None = None

    # Provided by FlowHandler
    async_show_form: Any
    async_show_menu: Any
    async_show_progress: Any
    async_show_progress_done: Any
    add_suggested_values_to_schema: Any

    async def _async_finish(self) -> FlowResult:
        """Store the commands and close the flow."""
        raise NotImplementedError

    def _other_commands(self) -> list[dict[str, Any]]:
        """Commands other than the one being re-learned."""
        return [c for c in self._commands if c[CMD_ID] != self._replace_id]

    @callback
    def _async_show_name_form(self, errors: dict[str, str] | None = None) -> FlowResult:
        schema = probatio.Schema({probatio.Optional(CONF_NAME): TextSelector()})
        learned = [c[CMD_NAME] for c in self._commands]
        return self.async_show_form(
            step_id="command_name",
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_NAME: self._pending_name} if errors else {}
            ),
            errors=errors,
            description_placeholders={
                "remote": self._remote_name,
                "learned": ", ".join(learned) if learned else "none yet",
            },
            last_step=False,
        )

    async def async_step_command_name(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask which button is next. Leave it empty to finish."""
        if user_input is None:
            self._pending_name = None
            return self._async_show_name_form()

        name = (user_input.get(CONF_NAME) or "").strip()
        if not name:
            return await self._async_finish()

        self._pending_name = name
        if any(c[CMD_NAME].casefold() == name.casefold() for c in self._commands):
            return self._async_show_name_form({CONF_NAME: "name_exists"})

        self._replace_id = None
        return await self.async_step_learn()

    async def async_step_learn(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Wait for the button press."""
        if self._learn_task is None:
            self._signal = None
            self._learn_task = self.hass.async_create_task(
                async_learn_signal(self.hass, self._receiver)
            )

        if not self._learn_task.done():
            return self.async_show_progress(
                step_id="learn",
                progress_action="wait_for_signal",
                progress_task=self._learn_task,
                description_placeholders={"name": self._pending_name or ""},
            )

        self._signal = self._learn_task.result()
        self._learn_task = None
        return self.async_show_progress_done(next_step_id="learn_done")

    async def async_step_learn_done(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Review the signal, or ask again when nothing arrived."""
        if self._signal is None:
            if self._replace_id is not None:
                return self._async_show_review(note="no_signal")
            return self._async_show_name_form({"base": "no_signal"})
        return self._async_show_review()

    @callback
    def _async_show_review(self, note: str | None = None) -> FlowResult:
        notes: list[str] = []
        if self._signal is None:
            notes.append(
                "Nothing was received in 30 seconds. Point the remote at the "
                "receiver from close by and try again."
            )
        else:
            if dup := find_duplicate(self._signal, self._other_commands()):
                notes.append(
                    f"This looks the same as **{dup}**. Check you pressed the "
                    "right button."
                )
            if self._signal.held_repeats:
                notes.append(
                    "You held the button. The repeats were removed, so this "
                    "sends one press."
                )
            if note == "sent":
                notes.append(
                    "Sent. If the device reacted, save it. If not, learn it again."
                )
            elif note == "send_failed":
                notes.append("The emitter could not send the command.")

        if self._signal is None:
            options = ["retry"]
        elif self._replace_id is not None:
            options = ["test", "save_finish", "retry"]
        else:
            options = ["test", "save_next", "save_finish", "retry"]

        return self.async_show_menu(
            step_id="review",
            menu_options=options,
            description_placeholders={
                "name": self._pending_name or "",
                "summary": self._signal.summary() if self._signal else "",
                "notes": "\n\n".join(notes),
            },
        )

    async def async_step_review(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the review menu."""
        return self._async_show_review()

    async def async_step_test(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Send the captured signal once through the emitter."""
        assert self._signal is not None
        async_mark_sent(self.hass, self._emitter)
        try:
            await async_send_command(
                self.hass,
                self._emitter,
                LearnedCommand(self._signal.timings, self._signal.modulation),
            )
        except HomeAssistantError:
            return self._async_show_review(note="send_failed")
        async_mark_sent(self.hass, self._emitter)
        return self._async_show_review(note="sent")

    async def async_step_retry(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Learn the same button again."""
        return await self.async_step_learn()

    @callback
    def _async_commit(self) -> None:
        """Add the pending command, or replace the one being re-learned."""
        assert self._signal is not None and self._pending_name is not None
        stored = self._signal.as_stored(self._pending_name)
        if self._replace_id is not None:
            self._commands = [
                {
                    **c,
                    CMD_TIMINGS: stored[CMD_TIMINGS],
                    CMD_MODULATION: stored[CMD_MODULATION],
                }
                if c[CMD_ID] == self._replace_id
                else c
                for c in self._commands
            ]
        else:
            self._commands = [*self._commands, {CMD_ID: uuid4().hex, **stored}]
        self._signal = None
        self._pending_name = None

    async def async_step_save_next(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Save and move on to the next button."""
        self._async_commit()
        return self._async_show_name_form()

    async def async_step_save_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Save and close."""
        self._async_commit()
        return await self._async_finish()


class LearnedRemoteConfigFlow(LearnLoopMixin, ConfigFlow, domain=DOMAIN):
    """Create a remote, then learn its buttons."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._commands = []

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the flow to manage commands."""
        return LearnedRemoteOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the remote and pick the emitter and receiver."""
        if not async_get_emitters(self.hass):
            return self.async_abort(reason="no_emitters")
        if not async_get_receivers(self.hass):
            return self.async_abort(reason="no_receivers")

        if user_input is not None:
            self._remote_name = user_input[CONF_NAME]
            self._emitter = user_input[CONF_EMITTER]
            self._receiver = user_input[CONF_RECEIVER]
            return self._async_show_name_form()

        emitters = async_get_emitters(self.hass)
        receivers = async_get_receivers(self.hass)
        suggested = {}
        if len(emitters) == 1:
            suggested[CONF_EMITTER] = emitters[0]
        if len(receivers) == 1:
            suggested[CONF_RECEIVER] = receivers[0]
        schema = probatio.Schema(
            {
                probatio.Required(CONF_NAME): TextSelector(),
                probatio.Required(CONF_EMITTER): _emitter_selector(self.hass),
                probatio.Required(CONF_RECEIVER): _receiver_selector(self.hass),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            last_step=False,
        )

    @override
    async def _async_finish(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._remote_name,
            data={CONF_EMITTER: self._emitter, CONF_RECEIVER: self._receiver},
            options={CONF_COMMANDS: self._commands},
        )


class LearnedRemoteOptionsFlow(LearnLoopMixin, OptionsFlow):
    """Manage the buttons of a remote."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show what can be done with the remote."""
        entry = self.config_entry
        self._remote_name = entry.title
        self._emitter = entry.data[CONF_EMITTER]
        self._receiver = entry.data[CONF_RECEIVER]
        self._commands = list(entry.options.get(CONF_COMMANDS, []))

        options = ["learn_more"]
        if self._commands:
            options += ["relearn", "rename", "delete"]
        options.append("settings")

        names = [c[CMD_NAME] for c in self._commands]
        return self.async_show_menu(
            step_id="init",
            menu_options=options,
            description_placeholders={
                "remote": self._remote_name,
                "count": str(len(names)),
                "learned": ", ".join(names) if names else "none yet",
            },
        )

    async def async_step_learn_more(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Learn new buttons."""
        return self._async_show_name_form()

    async def async_step_relearn(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a command to learn again."""
        if user_input is not None:
            self._replace_id = user_input[CONF_COMMAND]
            self._pending_name = next(
                c[CMD_NAME] for c in self._commands if c[CMD_ID] == self._replace_id
            )
            return await self.async_step_learn()

        return self.async_show_form(
            step_id="relearn",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_COMMAND): SelectSelector(
                        SelectSelectorConfig(options=_command_options(self._commands))
                    )
                }
            ),
            last_step=False,
        )

    async def async_step_rename(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Rename commands. One field per command."""
        errors: dict[str, str] = {}
        if user_input is not None:
            new_names = {
                c[CMD_ID]: (user_input.get(c[CMD_NAME]) or "").strip()
                for c in self._commands
            }
            folded = [n.casefold() for n in new_names.values()]
            if "" in folded:
                errors["base"] = "name_empty"
            elif len(set(folded)) != len(folded):
                errors["base"] = "name_exists"
            else:
                self._commands = [
                    {**c, CMD_NAME: new_names[c[CMD_ID]]} for c in self._commands
                ]
                return await self._async_finish()

        # The current name is the field key, so the label reads naturally
        schema = probatio.Schema(
            {probatio.Required(c[CMD_NAME]): TextSelector() for c in self._commands}
        )
        return self.async_show_form(
            step_id="rename",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input or {c[CMD_NAME]: c[CMD_NAME] for c in self._commands},
            ),
            errors=errors,
        )

    async def async_step_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delete commands."""
        if user_input is not None:
            remove = set(user_input[CONF_COMMANDS])
            self._commands = [c for c in self._commands if c[CMD_ID] not in remove]
            return await self._async_finish()

        return self.async_show_form(
            step_id="delete",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_COMMANDS, default=[]): SelectSelector(
                        SelectSelectorConfig(
                            options=_command_options(self._commands),
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the emitter or the receiver."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, **user_input}
            )
            return await self._async_finish()

        schema = probatio.Schema(
            {
                probatio.Required(CONF_EMITTER): _emitter_selector(self.hass),
                probatio.Required(CONF_RECEIVER): _receiver_selector(self.hass),
                probatio.Required(CONF_LISTEN): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_LISTEN: True, **self.config_entry.data}
            ),
        )

    @override
    async def _async_finish(self) -> ConfigFlowResult:
        return self.async_create_entry(data={CONF_COMMANDS: self._commands})
