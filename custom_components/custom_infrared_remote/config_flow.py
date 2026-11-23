"""Config and options flows for the Custom infrared remote integration.

The setup dialog only picks what the remote controls and which infrared
device it uses. Buttons are learned on the learning screen (panel.py),
which the dialog links to when it finishes and the device page opens later.
"""

from typing import Any, override
from uuid import uuid4

import probatio
from homeassistant.components.infrared import (
    DOMAIN as INFRARED_DOMAIN,
)
from homeassistant.components.infrared import (
    async_get_emitters,
    async_get_receivers,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
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
    CMD_NAME,
    CONF_COMMANDS,
    CONF_DEVICE_TYPE,
    CONF_EMITTER,
    CONF_HIDDEN_ROLES,
    CONF_RECEIVER,
    DOMAIN,
)
from .panel import panel_path
from .templates import TEMPLATES, get_template


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


class LearnedRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a remote: pick what it controls and the infrared device."""

    VERSION = 1

    _device_type: str

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the flow to manage the remote."""
        return LearnedRemoteOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick what the remote controls."""
        if not async_get_emitters(self.hass):
            return self.async_abort(reason="no_emitters")
        if not async_get_receivers(self.hass):
            return self.async_abort(reason="no_receivers")
        return self.async_show_menu(step_id="user", menu_options=list(TEMPLATES))

    async def _async_pick_type(self, device_type: str) -> ConfigFlowResult:
        self._device_type = device_type
        return await self.async_step_details()

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the device and pick the emitter and receiver."""
        template = get_template(self._device_type)
        if user_input is not None:
            # The link at the end of setup needs an ID before the entry exists
            await self.async_set_unique_id(uuid4().hex)
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_EMITTER: user_input[CONF_EMITTER],
                    CONF_RECEIVER: user_input[CONF_RECEIVER],
                    CONF_DEVICE_TYPE: self._device_type,
                },
                options={
                    CONF_COMMANDS: [],
                    # Only the common buttons come up; the rest start hidden
                    CONF_HIDDEN_ROLES: [r.key for r in template.roles if not r.default],
                },
                description_placeholders={"link": panel_path(self.unique_id or "")},
            )

        emitters = async_get_emitters(self.hass)
        receivers = async_get_receivers(self.hass)
        suggested: dict[str, Any] = {}
        if template.suggested_name:
            suggested[CONF_NAME] = template.suggested_name
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
            step_id="details",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
        )


def _type_step(device_type: str) -> Any:
    async def step(
        self: LearnedRemoteConfigFlow, user_input: Any = None
    ) -> ConfigFlowResult:
        return await self._async_pick_type(device_type)

    step.__doc__ = f"Pick {device_type}."
    return step


# One menu step per device type
for _device_type in TEMPLATES:
    setattr(
        LearnedRemoteConfigFlow, f"async_step_{_device_type}", _type_step(_device_type)
    )


class LearnedRemoteOptionsFlow(OptionsFlow):
    """Rename and delete buttons, or change the infrared device.

    Learning happens on the learning screen, which this menu links to.
    """

    _commands: list[dict[str, Any]]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show what can be done with the remote."""
        entry = self.config_entry
        self._commands = list(entry.options.get(CONF_COMMANDS, []))
        options = ["rename", "delete"] if self._commands else []
        options.append("settings")
        return self.async_show_menu(
            step_id="init",
            menu_options=options,
            description_placeholders={
                "remote": entry.title,
                "link": panel_path(entry.entry_id),
            },
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
            data = {**self.config_entry.data, **user_input}
            # Listening used to be a setting here; the event entity is now
            # always created and can be disabled like any other entity
            data.pop("listen", None)
            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return await self._async_finish()

        schema = probatio.Schema(
            {
                probatio.Required(CONF_EMITTER): _emitter_selector(self.hass),
                probatio.Required(CONF_RECEIVER): _receiver_selector(self.hass),
            }
        )
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(
                schema, dict(self.config_entry.data)
            ),
        )

    async def _async_finish(self) -> ConfigFlowResult:
        return self.async_create_entry(
            data={**self.config_entry.options, CONF_COMMANDS: self._commands}
        )
