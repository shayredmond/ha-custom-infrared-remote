"""Guided capture: pick the buttons your remote has, then press them in turn.

Like mapping a controller in RetroArch: the wizard names the button, you
press it, and it moves on to the next one by itself as soon as the signal
arrives. It only stops when something needs a decision: nothing arrived,
or the signal is the same as a button already learned.
"""

import asyncio
from typing import Any
from uuid import uuid4

import probatio
from homeassistant.components.infrared import async_send_command
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CAPTURE_TIMEOUT,
    CMD_ID,
    CMD_MODULATION,
    CMD_NAME,
    CMD_ROLE,
    CMD_TIMINGS,
)
from .signal import (
    LearnedCommand,
    LearnedSignal,
    async_learn_signal,
    async_mark_sent,
    find_duplicate,
)
from .templates import DeviceTemplate, get_template

CONF_BUTTONS = "buttons"
CONF_BUTTON = "button"


class GuidedCaptureMixin:
    """Steps for the guided capture. Mixed into the config and options flows."""

    hass: HomeAssistant
    _remote_name: str
    _emitter: str
    _receiver: str
    _commands: list[dict[str, Any]]
    _hidden_roles: list[str]
    _device_type: str | None

    _queue: list[str]
    _queue_pos: int = 0
    _queue_done: list[str]
    _capture_task: asyncio.Task[LearnedSignal | None] | None = None
    _captured: LearnedSignal | None = None
    _ready_note: str = ""

    # Provided by FlowHandler and LearnLoopMixin
    async_show_form: Any
    async_show_menu: Any
    async_show_progress: Any
    async_show_progress_done: Any
    add_suggested_values_to_schema: Any

    # Provided by the flow classes and LearnLoopMixin
    _async_finish: Any
    _async_show_name_form: Any

    @property
    def _template(self) -> DeviceTemplate:
        return get_template(self._device_type)

    def _learned_roles(self) -> set[str]:
        return {c[CMD_ROLE] for c in self._commands if c.get(CMD_ROLE)}

    def _missing_roles(self) -> list[str]:
        learned = self._learned_roles()
        return [r.key for r in self._template.roles if r.key not in learned]

    # Pick the buttons

    async def async_step_buttons(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Tick the buttons your remote has, grouped into sections.

        Unticked buttons are stored as hidden ("don't learn it"), so they stay
        unticked next time. The learning screen beta uses the same key.
        """
        missing = self._missing_roles()
        if user_input is not None:
            chosen = {
                key
                for group in user_input.values()
                if isinstance(group, dict)
                for key in group.get(CONF_BUTTONS, [])
            }
            hidden = set(self._hidden_roles) - set(missing)
            self._hidden_roles = [
                r.key
                for r in self._template.roles
                if r.key in hidden or (r.key in missing and r.key not in chosen)
            ]
            return await self._async_start_capture([k for k in missing if k in chosen])

        template = self._template
        hidden = set(self._hidden_roles)
        groups: dict[str, list[str]] = {}
        for key in missing:
            groups.setdefault(template.role(key).group, []).append(key)  # type: ignore[union-attr]

        schema: dict[Any, Any] = {}
        for group, keys in groups.items():
            defaults = [k for k in keys if k not in hidden]
            schema[probatio.Optional(group, default={})] = section(
                probatio.Schema(
                    {
                        probatio.Optional(CONF_BUTTONS, default=defaults): (
                            SelectSelector(
                                SelectSelectorConfig(
                                    options=[
                                        SelectOptionDict(
                                            value=k,
                                            label=template.role(k).name,  # type: ignore[union-attr]
                                        )
                                        for k in keys
                                    ],
                                    multiple=True,
                                    mode=SelectSelectorMode.LIST,
                                )
                            )
                        )
                    }
                ),
                {"collapsed": not defaults and len(groups) > 1},
            )
        return self.async_show_form(
            step_id="buttons",
            data_schema=probatio.Schema(schema),
            description_placeholders={
                "remote": self._remote_name,
                "timeout": str(CAPTURE_TIMEOUT),
            },
            last_step=False,
        )

    # Capture, one button after another

    async def _async_start_capture(self, roles: list[str]) -> FlowResult:
        self._queue = roles
        self._queue_pos = 0
        self._queue_done = []
        if not roles:
            return self._async_show_ready()
        return await self._async_capture()

    def _checklist(self) -> str:
        template = self._template
        lines = []
        for index, key in enumerate(self._queue):
            name = template.role(key).name  # type: ignore[union-attr]
            if key in self._queue_done:
                lines.append(f"✓ {name}")
            elif index == self._queue_pos:
                lines.append(f"**→ {name}**")
            elif index < self._queue_pos:
                lines.append(f"{name} (skipped)")
            else:
                lines.append(name)
        # Two trailing spaces make a markdown line break
        return "  \n".join(lines)

    async def _async_capture(self) -> FlowResult:
        if self._capture_task is None:
            self._captured = None
            self._capture_task = self.hass.async_create_task(
                async_learn_signal(self.hass, self._receiver, CAPTURE_TIMEOUT)
            )

        if not self._capture_task.done():
            role = self._template.role(self._queue[self._queue_pos])
            # Alternate step IDs: the frontend can stall when a progress step
            # is followed by another progress step with the same ID.
            step_id = "capture" if self._queue_pos % 2 == 0 else "capture_next"
            return self.async_show_progress(
                step_id=step_id,
                progress_action="press_button",
                progress_task=self._capture_task,
                description_placeholders={
                    "name": role.name,  # type: ignore[union-attr]
                    "position": str(self._queue_pos + 1),
                    "total": str(len(self._queue)),
                    "checklist": self._checklist(),
                    "timeout": str(CAPTURE_TIMEOUT),
                },
            )

        self._captured = self._capture_task.result()
        self._capture_task = None
        return self.async_show_progress_done(next_step_id="captured")

    async def async_step_capture(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Wait for the button press."""
        return await self._async_capture()

    async def async_step_capture_next(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Wait for the button press (alternate step ID)."""
        return await self._async_capture()

    def _current_role_key(self) -> str:
        return self._queue[self._queue_pos]

    def _duplicate_of(self, signal: LearnedSignal) -> str | None:
        key = self._current_role_key()
        others = [c for c in self._commands if c.get(CMD_ROLE) != key]
        return find_duplicate(signal, others)

    async def async_step_captured(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Move on, or stop when something needs a decision."""
        if self._captured is None:
            return await self.async_step_capture_missed()
        if self._duplicate_of(self._captured):
            return await self.async_step_capture_duplicate()
        self._async_commit_role()
        return await self._async_advance()

    def _current_name(self) -> str:
        return self._template.role(self._current_role_key()).name  # type: ignore[union-attr]

    async def async_step_capture_missed(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Nothing arrived: try again, skip or stop."""
        return self.async_show_menu(
            step_id="capture_missed",
            menu_options=["capture_retry", "capture_skip", "capture_stop"],
            description_placeholders={
                "name": self._current_name(),
                "timeout": str(CAPTURE_TIMEOUT),
            },
        )

    async def async_step_capture_duplicate(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Same as another button: press again, keep or skip."""
        assert self._captured is not None
        return self.async_show_menu(
            step_id="capture_duplicate",
            menu_options=["capture_retry", "capture_accept", "capture_skip"],
            description_placeholders={
                "name": self._current_name(),
                "duplicate": self._duplicate_of(self._captured) or "",
            },
        )

    async def async_step_capture_retry(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Press the same button again."""
        return await self._async_capture()

    async def async_step_capture_accept(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Keep the signal even though it matches another button."""
        self._async_commit_role()
        return await self._async_advance()

    async def async_step_capture_skip(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Skip this button."""
        return await self._async_advance()

    async def async_step_capture_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Stop capturing and keep what was learned."""
        return self._async_show_ready()

    @callback
    def _async_commit_role(self) -> None:
        assert self._captured is not None
        key = self._current_role_key()
        stored = self._captured.as_stored(self._current_name())
        existing = next((c for c in self._commands if c.get(CMD_ROLE) == key), None)
        if existing:
            self._commands = [
                {
                    **c,
                    CMD_TIMINGS: stored[CMD_TIMINGS],
                    CMD_MODULATION: stored[CMD_MODULATION],
                }
                if c is existing
                else c
                for c in self._commands
            ]
        else:
            self._commands = [
                *self._commands,
                {CMD_ID: uuid4().hex, CMD_ROLE: key, **stored},
            ]
        self._queue_done.append(key)
        self._captured = None

    async def _async_advance(self) -> FlowResult:
        self._queue_pos += 1
        if self._queue_pos < len(self._queue):
            return await self._async_capture()
        return self._async_show_ready()

    # Ready: test, fix, add more, finish

    @callback
    def _async_show_ready(self) -> FlowResult:
        options = []
        if self._commands:
            options.append("ready_test")
        if self._learned_roles():
            options.append("ready_relearn")
        if self._missing_roles():
            options.append("ready_more")
        options += ["ready_custom", "ready_finish"]

        learned = self._learned_roles()
        features = [
            r.name
            for r in self._template.roles
            if r.key in learned and r.key in self._template.mapped
        ]
        extras = [
            c[CMD_NAME]
            for c in self._commands
            if c.get(CMD_ROLE) not in self._template.mapped
        ]
        note, self._ready_note = self._ready_note, ""
        return self.async_show_menu(
            step_id="ready",
            menu_options=options,
            description_placeholders={
                "remote": self._remote_name,
                "controls": ", ".join(features) if features else "none",
                "buttons": ", ".join(extras) if extras else "none",
                "note": note,
            },
        )

    async def async_step_ready(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the ready menu."""
        return self._async_show_ready()

    def _button_selector(self, roles_only: bool = False) -> SelectSelector:
        commands = [c for c in self._commands if not roles_only or c.get(CMD_ROLE)]
        return SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=c[CMD_ID], label=c[CMD_NAME])
                    for c in commands
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )

    async def async_step_ready_test(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Send one button to check it works."""
        if user_input is not None:
            command = next(
                c for c in self._commands if c[CMD_ID] == user_input[CONF_BUTTON]
            )
            async_mark_sent(self.hass, self._emitter)
            try:
                await async_send_command(
                    self.hass, self._emitter, LearnedCommand.from_stored(command)
                )
            except HomeAssistantError:
                self._ready_note = "The emitter could not send the command."
            else:
                async_mark_sent(self.hass, self._emitter)
                self._ready_note = (
                    f"Sent **{command[CMD_NAME]}**. If the device didn't react, "
                    "learn it again."
                )
            return self._async_show_ready()

        return self.async_show_form(
            step_id="ready_test",
            data_schema=probatio.Schema(
                {probatio.Required(CONF_BUTTON): self._button_selector()}
            ),
            last_step=False,
        )

    async def async_step_ready_relearn(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Press one button again."""
        if user_input is not None:
            command = next(
                c for c in self._commands if c[CMD_ID] == user_input[CONF_BUTTON]
            )
            return await self._async_start_capture([command[CMD_ROLE]])

        return self.async_show_form(
            step_id="ready_relearn",
            data_schema=probatio.Schema(
                {probatio.Required(CONF_BUTTON): self._button_selector(True)}
            ),
            last_step=False,
        )

    async def async_step_ready_more(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick more of the suggested buttons."""
        return await self.async_step_buttons()

    async def async_step_ready_custom(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Name and learn buttons that aren't in the list."""
        return self._async_show_name_form()

    async def async_step_ready_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Save and close."""
        return await self._async_finish()
