"""The learning screen: a full-page panel and the websocket API behind it.

The panel isn't in the sidebar. It opens from the setup dialog and from the
device page (the device's configuration URL), one remote at a time:
/custom-infrared-remote/<entry_id>.
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

import probatio
from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.infrared import (
    InfraredReceivedSignal,
    async_send_command,
    async_subscribe_receiver,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import (
    CMD_ID,
    CMD_MODULATION,
    CMD_NAME,
    CMD_ROLE,
    CMD_TIMINGS,
    CONF_COMMANDS,
    CONF_EMITTER,
    CONF_HIDDEN_ROLES,
    CONF_RECEIVER,
    DOMAIN,
    MIN_TIMINGS,
)
from .signal import (
    LearnedCommand,
    LearnedSignal,
    async_mark_sent,
    async_recently_sent,
    find_best_match,
)
from .templates import entry_template

PANEL_URL = "custom-infrared-remote"
STATIC_URL = f"/{DOMAIN}_static"
WEBCOMPONENT = "custom-infrared-remote-panel"
DATA_CAPTURES = f"{DOMAIN}_captures"
DATA_LEARNING = f"{DOMAIN}_learning"
MAX_CAPTURES = 20


@callback
def async_is_learning(hass: HomeAssistant, entry_id: str) -> bool:
    """Return True while the learning screen listens for this remote."""
    return entry_id in hass.data.get(DATA_LEARNING, {})


def panel_path(entry_id: str) -> str:
    """Return the frontend path of the learning screen for a remote."""
    return f"/{PANEL_URL}/{entry_id}"


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register the panel, its script and the websocket commands."""
    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(frontend_dir), cache_headers=False)]
    )
    version = (frontend_dir / "panel.js").stat().st_mtime_ns
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        frontend_url_path=PANEL_URL,
        require_admin=True,
        show_in_sidebar=False,
        config={
            "_panel_custom": {
                "name": WEBCOMPONENT,
                "module_url": f"{STATIC_URL}/panel.js?v={version}",
                "embed_iframe": False,
                "trust_external": False,
            }
        },
    )
    for command in (
        ws_get,
        ws_capture,
        ws_assign,
        ws_hide,
        ws_delete,
        ws_test,
    ):
        websocket_api.async_register_command(hass, command)


def _entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry:
    """Find a remote by entry ID, or by the unique ID the setup dialog links to."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise HomeAssistantError(f"No remote with ID {entry_id}")
    return entry


def _commands(entry: ConfigEntry) -> list[dict[str, Any]]:
    return list(entry.options.get(CONF_COMMANDS, []))


def _hidden(entry: ConfigEntry) -> list[str]:
    return list(entry.options.get(CONF_HIDDEN_ROLES, []))


@callback
def _save(
    hass: HomeAssistant,
    entry: ConfigEntry,
    commands: list[dict[str, Any]] | None = None,
    hidden: list[str] | None = None,
) -> None:
    options = dict(entry.options)
    if commands is not None:
        options[CONF_COMMANDS] = commands
    if hidden is not None:
        options[CONF_HIDDEN_ROLES] = hidden
    hass.config_entries.async_update_entry(entry, options=options)


def _friendly(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    return state.name if state else entity_id


def _state(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Everything the screen needs to draw one remote."""
    template = entry_template(entry)
    commands = _commands(entry)
    by_role = {c[CMD_ROLE]: c for c in commands if c.get(CMD_ROLE)}
    hidden = set(_hidden(entry))
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "device_type": template.key,
        "device_id": device.id if device else None,
        "receiver": _friendly(hass, entry.data[CONF_RECEIVER]),
        "roles": [
            {
                "key": role.key,
                "name": role.name,
                "group": role.group,
                "learned": role.key in by_role,
                "command_id": by_role[role.key][CMD_ID]
                if role.key in by_role
                else None,
                "hidden": role.key in hidden,
            }
            for role in template.roles
        ],
        "custom": [
            {"id": c[CMD_ID], "name": c[CMD_NAME]}
            for c in commands
            if not c.get(CMD_ROLE) or not template.role(c[CMD_ROLE])
        ],
    }


@websocket_api.websocket_command(
    {probatio.Required("type"): f"{DOMAIN}/get", probatio.Required("entry_id"): str}
)
@websocket_api.require_admin
@callback
def ws_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Return the remote's buttons."""
    try:
        entry = _entry(hass, msg["entry_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    connection.send_result(msg["id"], _state(hass, entry))


@websocket_api.websocket_command(
    {
        probatio.Required("type"): f"{DOMAIN}/capture",
        probatio.Required("entry_id"): str,
    }
)
@websocket_api.require_admin
@callback
def ws_capture(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Listen to the receiver while the screen is open.

    Every real signal is kept under a token and sent to the screen, which
    then assigns it to the highlighted row. Signals heard right after
    something was sent through the emitter are our own echo and ignored.
    """
    try:
        entry = _entry(hass, msg["entry_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    emitter = entry.data[CONF_EMITTER]
    captures: dict[str, LearnedSignal] = hass.data.setdefault(DATA_CAPTURES, {})

    @callback
    def _on_signal(signal: InfraredReceivedSignal) -> None:
        if len(signal.timings) < MIN_TIMINGS or async_recently_sent(hass, emitter):
            return
        learned = LearnedSignal.from_received(signal)
        token = uuid4().hex
        captures[token] = learned
        while len(captures) > MAX_CAPTURES:
            captures.pop(next(iter(captures)))
        match = find_best_match(learned.timings, _commands(entry))
        connection.send_message(
            websocket_api.event_message(
                msg["id"],
                {
                    "token": token,
                    "summary": learned.summary(),
                    "matches": match[CMD_NAME] if match else None,
                },
            )
        )

    try:
        unsubscribe = async_subscribe_receiver(
            hass, entry.data[CONF_RECEIVER], _on_signal
        )
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "receiver_unavailable", str(err))
        return
    # While the screen listens, the remote's event entity stays quiet, so
    # learning buttons doesn't set off automations
    learning: dict[str, int] = hass.data.setdefault(DATA_LEARNING, {})
    learning[entry.entry_id] = learning.get(entry.entry_id, 0) + 1

    @callback
    def _stop() -> None:
        unsubscribe()
        learning[entry.entry_id] -= 1
        if not learning[entry.entry_id]:
            del learning[entry.entry_id]

    connection.subscriptions[msg["id"]] = _stop
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        probatio.Required("type"): f"{DOMAIN}/assign",
        probatio.Required("entry_id"): str,
        probatio.Required("token"): str,
        probatio.Exclusive("role", "target"): str,
        probatio.Exclusive("command_id", "target"): str,
        probatio.Exclusive("name", "target"): str,
        probatio.Optional("allow_duplicate", default=False): bool,
    }
)
@websocket_api.require_admin
@callback
def ws_assign(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Save a captured signal to a suggested button, a button, or a new one."""
    try:
        entry = _entry(hass, msg["entry_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    signal = hass.data.get(DATA_CAPTURES, {}).get(msg["token"])
    if signal is None:
        connection.send_error(msg["id"], "expired", "Press the button again")
        return

    template = entry_template(entry)
    commands = _commands(entry)
    hidden = _hidden(entry)
    role_key = msg.get("role")
    command_id = msg.get("command_id")
    name = (msg.get("name") or "").strip()

    if role_key:
        role = template.role(role_key)
        if role is None:
            connection.send_error(msg["id"], "invalid", f"Unknown button {role_key}")
            return
        target = next((c for c in commands if c.get(CMD_ROLE) == role_key), None)
        name = role.name
    elif command_id:
        target = next((c for c in commands if c[CMD_ID] == command_id), None)
        if target is None:
            connection.send_error(msg["id"], "invalid", "Unknown button")
            return
        name = target[CMD_NAME]
    else:
        target = None
        if not name:
            connection.send_error(msg["id"], "invalid", "Give the button a name")
            return
        if any(c[CMD_NAME].casefold() == name.casefold() for c in commands):
            connection.send_error(msg["id"], "name_exists", f"{name} already exists")
            return

    others = [c for c in commands if c is not target]
    if not msg["allow_duplicate"] and (dup := find_best_match(signal.timings, others)):
        connection.send_result(msg["id"], {"duplicate": dup[CMD_NAME]})
        return

    stored = signal.as_stored(name)
    if target is not None:
        saved_id = target[CMD_ID]
        commands = [
            {
                **c,
                CMD_TIMINGS: stored[CMD_TIMINGS],
                CMD_MODULATION: stored[CMD_MODULATION],
            }
            if c is target
            else c
            for c in commands
        ]
    else:
        saved_id = uuid4().hex
        new = {CMD_ID: saved_id, **stored}
        if role_key:
            new[CMD_ROLE] = role_key
        commands.append(new)
    if role_key in hidden:
        hidden.remove(role_key)
    _save(hass, entry, commands, hidden)
    connection.send_result(msg["id"], {"saved": saved_id})


@websocket_api.websocket_command(
    {
        probatio.Required("type"): f"{DOMAIN}/hide",
        probatio.Required("entry_id"): str,
        probatio.Required("role"): str,
        probatio.Required("hidden"): bool,
    }
)
@websocket_api.require_admin
@callback
def ws_hide(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Hide a suggested button (forgetting it if learned), or show it again."""
    try:
        entry = _entry(hass, msg["entry_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    role_key = msg["role"]
    hidden = [r for r in _hidden(entry) if r != role_key]
    commands = _commands(entry)
    if msg["hidden"]:
        hidden.append(role_key)
        commands = [c for c in commands if c.get(CMD_ROLE) != role_key]
    _save(hass, entry, commands, hidden)
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        probatio.Required("type"): f"{DOMAIN}/delete",
        probatio.Required("entry_id"): str,
        probatio.Required("command_id"): str,
    }
)
@websocket_api.require_admin
@callback
def ws_delete(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Delete one of your own buttons."""
    try:
        entry = _entry(hass, msg["entry_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    commands = [c for c in _commands(entry) if c[CMD_ID] != msg["command_id"]]
    _save(hass, entry, commands)
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        probatio.Required("type"): f"{DOMAIN}/test",
        probatio.Required("entry_id"): str,
        probatio.Required("command_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_test(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Send a learned button through the emitter."""
    try:
        entry = _entry(hass, msg["entry_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    command = next(
        (c for c in _commands(entry) if c[CMD_ID] == msg["command_id"]), None
    )
    if command is None:
        connection.send_error(msg["id"], "invalid", "Unknown button")
        return
    emitter = entry.data[CONF_EMITTER]
    async_mark_sent(hass, emitter)
    try:
        await async_send_command(hass, emitter, LearnedCommand.from_stored(command))
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "send_failed", str(err))
        return
    async_mark_sent(hass, emitter)
    connection.send_result(msg["id"])
