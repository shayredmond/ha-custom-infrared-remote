// Learning screen for Custom infrared remote.
//
// One remote at a time, at /custom-infrared-remote/<entry_id>. The list of
// suggested buttons has one highlighted row: press that button on the
// remote and it's learned, then the highlight moves to the next row by
// itself. Every row can be skipped or hidden. Plain web component, no build
// step; styled with Home Assistant's theme variables.

const DOMAIN = "custom_infrared_remote";

const GROUPS = {
  power: "Power",
  volume: "Volume",
  channels: "Channels",
  inputs: "Inputs",
  playback: "Playback",
  navigation: "Navigation",
  controls: "Controls",
};

const STYLE = `
  :host {
    display: block;
    min-height: 100vh;
    background: var(--primary-background-color);
    color: var(--primary-text-color);
    font-family: var(--ha-font-family-body, Roboto, sans-serif);
  }
  header {
    position: sticky; top: 0; z-index: 2;
    display: flex; align-items: center; gap: 4px;
    height: 56px; padding: 0 8px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, white);
    border-bottom: var(--app-header-border-bottom, none);
  }
  header h1 { font-size: 20px; font-weight: 400; margin: 0 0 0 8px; flex: 1;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .icon-btn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 40px; height: 40px; border-radius: 50%; border: none;
    background: none; color: inherit; cursor: pointer; padding: 0;
  }
  .icon-btn:hover { background: rgba(127,127,127,0.15); }
  .icon-btn[disabled] { opacity: 0.4; cursor: default; }
  main { max-width: 720px; margin: 0 auto; padding: 16px 16px 24px; }
  .card {
    background: var(--card-background-color);
    border-radius: var(--ha-card-border-radius, 12px);
    border: 1px solid var(--divider-color);
    margin-bottom: 16px; overflow: hidden;
  }
  .status { display: flex; align-items: center; gap: 12px; padding: 16px; }
  .status .text { flex: 1; }
  .status .title { font-size: 16px; font-weight: 500; }
  .status .sub { color: var(--secondary-text-color); font-size: 14px; margin-top: 2px; }
  .dot { width: 12px; height: 12px; border-radius: 50%; flex: none;
    background: var(--primary-color); animation: pulse 1.2s infinite; }
  .dot.idle { background: var(--success-color, #43a047); animation: none; }
  .dot.off { background: var(--disabled-color, #bdbdbd); animation: none; }
  @keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.35; transform: scale(0.8); } }
  h2 { font-size: 14px; font-weight: 500; letter-spacing: 0.1px;
    color: var(--secondary-text-color); margin: 0; padding: 12px 16px 4px; }
  .row {
    display: flex; align-items: center; gap: 12px;
    min-height: 56px; padding: 4px 8px 4px 16px;
    border-left: 4px solid transparent;
    transition: background 0.2s, border-color 0.2s;
  }
  .row + .row { border-top: 1px solid var(--divider-color); }
  .row.current {
    background: rgba(var(--rgb-primary-color, 3,169,244), 0.12);
    border-left-color: var(--primary-color);
  }
  .row.hidden { opacity: 0.5; }
  .row .state { width: 24px; height: 24px; flex: none; color: var(--secondary-text-color); }
  .row.learned .state { color: var(--success-color, #43a047); }
  .row.current .state { color: var(--primary-color); }
  .row .label { flex: 1; min-width: 0; }
  .row .name { font-size: 16px; }
  .row .hint { font-size: 13px; color: var(--secondary-text-color); margin-top: 1px; }
  .row.current .hint { color: var(--primary-color); font-weight: 500; }
  .row .warn { font-size: 13px; color: var(--warning-color, #ffa600); margin-top: 2px; }
  .text-btn {
    border: none; background: none; cursor: pointer;
    color: var(--primary-color); font: inherit; font-size: 14px; font-weight: 500;
    padding: 8px 12px; border-radius: 18px;
  }
  .text-btn:hover { background: rgba(var(--rgb-primary-color, 3,169,244), 0.1); }
  .filled-btn {
    border: none; cursor: pointer; font: inherit; font-size: 14px; font-weight: 500;
    background: var(--primary-color); color: var(--text-primary-color, white);
    padding: 10px 20px; border-radius: 20px;
  }
  .add { display: flex; gap: 8px; align-items: center; padding: 12px 16px; }
  .add input {
    flex: 1; font: inherit; font-size: 16px; padding: 10px 12px;
    border-radius: 8px; border: 1px solid var(--divider-color);
    background: var(--input-fill-color, var(--secondary-background-color));
    color: var(--primary-text-color);
  }
  .empty { padding: 12px 16px 16px; color: var(--secondary-text-color); font-size: 14px; }
  footer {
    position: sticky; bottom: 0; z-index: 2;
    display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px;
    background: var(--card-background-color);
    border-top: 1px solid var(--divider-color);
  }
  .error { padding: 24px; color: var(--error-color, #db4437); }
`;

const ICON = {
  back: "mdi:arrow-left",
  current: "mdi:remote",
  learned: "mdi:check-circle",
  pending: "mdi:circle-outline",
  skipped: "mdi:debug-step-over",
  hidden: "mdi:eye-off-outline",
  hide: "mdi:eye-off",
  show: "mdi:eye",
  test: "mdi:play",
  delete: "mdi:delete-outline",
};

const esc = (text) =>
  String(text).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

class CustomInfraredRemotePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._error = null;
    this._skipped = new Set();
    this._target = null; // explicit target: {role} | {command_id} | {name}
    this._warning = null; // {key, duplicate, token}
    this._note = null;
    this._unsub = null;
    this._entryId = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._load();
  }

  set route(route) {
    const id = (route?.path || "").replace(/^\//, "").split("/")[0];
    if (id && id !== this._entryId) {
      this._entryId = id;
      if (this._hass) this._load();
    }
  }

  set narrow(_narrow) {}
  set panel(_panel) {}

  disconnectedCallback() {
    this._stopListening();
  }

  // Data

  async _load() {
    if (!this._hass || !this._entryId) return;
    try {
      this._data = await this._hass.callWS({
        type: `${DOMAIN}/get`,
        entry_id: this._entryId,
      });
      // The link from setup uses the unique ID; from here on use the entry ID
      this._entryId = this._data.entry_id;
      this._error = null;
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._render();
    if (this._data && !this._unsub) this._startListening();
  }

  async _startListening() {
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (event) => this._onCapture(event),
        { type: `${DOMAIN}/capture`, entry_id: this._entryId },
      );
      this._render();
    } catch (err) {
      this._note = `Can't listen to the receiver: ${err.message || err}`;
      this._render();
    }
  }

  _stopListening() {
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  // Which row is highlighted

  _visibleRoles() {
    return this._data.roles.filter((r) => !r.hidden);
  }

  _current() {
    if (this._target) return this._target;
    const next = this._visibleRoles().find(
      (r) => !r.learned && !this._skipped.has(r.key),
    );
    return next ? { role: next.key } : null;
  }

  _isCurrent(target) {
    const cur = this._current();
    if (!cur) return false;
    return (
      (target.role && cur.role === target.role) ||
      (target.command_id && cur.command_id === target.command_id) ||
      (target.name !== undefined && cur.name !== undefined)
    );
  }

  _targetLabel(target) {
    if (target.role) return this._data.roles.find((r) => r.key === target.role).name;
    if (target.command_id)
      return this._data.custom.find((c) => c.id === target.command_id)?.name;
    return target.name;
  }

  // Capturing

  async _onCapture(event) {
    const target = this._current();
    if (!target) {
      this._note = event.matches
        ? `Heard ${event.matches}.`
        : "Heard a button that isn't learned. Pick a row to learn it.";
      this._render();
      return;
    }
    await this._assign(target, event.token, false);
  }

  async _assign(target, token, allowDuplicate) {
    const key = target.role || target.command_id || "new";
    try {
      const result = await this._hass.callWS({
        type: `${DOMAIN}/assign`,
        entry_id: this._entryId,
        token,
        allow_duplicate: allowDuplicate,
        ...target,
      });
      if (result.duplicate) {
        this._warning = { key, duplicate: result.duplicate, token };
        this._render();
        return;
      }
      this._warning = null;
      this._note = `${this._targetLabel(target)} learned.`;
      if (target.role) this._skipped.delete(target.role);
      this._target = null;
      await this._load();
      this._scrollToCurrent();
    } catch (err) {
      this._note = err.message || String(err);
      this._render();
    }
  }

  _scrollToCurrent() {
    const row = this.shadowRoot.querySelector(".row.current");
    if (row) row.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  // Row actions

  async _action(action, value) {
    const call = (msg) => this._hass.callWS({ entry_id: this._entryId, ...msg });
    this._note = null;
    switch (action) {
      case "skip":
        this._skipped.add(value);
        if (this._target?.role === value) this._target = null;
        this._warning = null;
        break;
      case "learn-role":
        this._skipped.delete(value);
        this._target = { role: value };
        this._warning = null;
        break;
      case "learn-command":
        this._target = { command_id: value };
        this._warning = null;
        break;
      case "keep": {
        const target = this._current();
        await this._assign(target, this._warning.token, true);
        return;
      }
      case "hide":
        if (this._target?.role === value) this._target = null;
        await call({ type: `${DOMAIN}/hide`, role: value, hidden: true });
        await this._load();
        return;
      case "show":
        await call({ type: `${DOMAIN}/hide`, role: value, hidden: false });
        this._skipped.delete(value);
        await this._load();
        return;
      case "test":
        try {
          await call({ type: `${DOMAIN}/test`, command_id: value });
          this._note = "Sent.";
        } catch (err) {
          this._note = err.message || String(err);
        }
        break;
      case "delete":
        if (this._target?.command_id === value) this._target = null;
        await call({ type: `${DOMAIN}/delete`, command_id: value });
        await this._load();
        return;
      case "add": {
        const input = this.shadowRoot.querySelector("#new-name");
        const name = input.value.trim();
        if (!name) return;
        if (this._data.custom.some((c) => c.name.toLowerCase() === name.toLowerCase())) {
          this._note = `${name} already exists.`;
          break;
        }
        this._target = { name };
        this._warning = null;
        break;
      }
      case "cancel":
        this._target = null;
        this._warning = null;
        break;
      case "done":
        this._navigate(
          this._data.device_id
            ? `/config/devices/device/${this._data.device_id}`
            : "/config/integrations/integration/custom_infrared_remote",
        );
        return;
      case "back":
        history.back();
        return;
    }
    this._render();
    this._scrollToCurrent();
  }

  _navigate(path) {
    history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  // Rendering

  _btn(action, value, label) {
    return `<button class="text-btn" data-action="${action}" data-value="${esc(value)}">${label}</button>`;
  }

  _iconBtn(action, value, icon, title) {
    return `<button class="icon-btn" data-action="${action}" data-value="${esc(value)}" title="${title}" aria-label="${title}"><ha-icon icon="${icon}"></ha-icon></button>`;
  }

  _roleRow(role) {
    const current = this._isCurrent({ role: role.key });
    const skipped = this._skipped.has(role.key);
    let cls = "row";
    let icon = ICON.pending;
    let hint = "";
    const actions = [];

    if (role.hidden) {
      cls += " hidden";
      icon = ICON.hidden;
      hint = "Hidden: not on your remote";
      actions.push(this._iconBtn("show", role.key, ICON.show, "Show"));
    } else if (current) {
      cls += " current";
      icon = ICON.current;
      hint = role.learned
        ? "Press it on your remote to learn it again"
        : "Press it on your remote now";
      if (role.learned) actions.push(this._btn("cancel", "", "Cancel"));
      else actions.push(this._btn("skip", role.key, "Skip"));
      actions.push(this._iconBtn("hide", role.key, ICON.hide, "Hide"));
    } else if (role.learned) {
      cls += " learned";
      icon = ICON.learned;
      hint = "Learned";
      actions.push(this._iconBtn("test", role.command_id, ICON.test, "Send it"));
      actions.push(this._btn("learn-role", role.key, "Relearn"));
      actions.push(this._iconBtn("hide", role.key, ICON.hide, "Hide"));
    } else if (skipped) {
      icon = ICON.skipped;
      hint = "Skipped";
      actions.push(this._btn("learn-role", role.key, "Learn"));
      actions.push(this._iconBtn("hide", role.key, ICON.hide, "Hide"));
    } else {
      actions.push(this._btn("skip", role.key, "Skip"));
      actions.push(this._iconBtn("hide", role.key, ICON.hide, "Hide"));
    }

    const warn =
      current && this._warning?.key === role.key
        ? `<div class="warn">That's the same signal as ${esc(this._warning.duplicate)}. Press ${esc(role.name)} again, or ${this._btn("keep", "", "keep it anyway")}</div>`
        : "";
    return `<div class="${cls}" data-key="${role.key}">
      <ha-icon class="state" icon="${icon}"></ha-icon>
      <div class="label"><div class="name">${esc(role.name)}</div><div class="hint">${hint}</div>${warn}</div>
      ${actions.join("")}
    </div>`;
  }

  _customRow(command) {
    const current = this._isCurrent({ command_id: command.id });
    const warn =
      current && this._warning?.key === command.id
        ? `<div class="warn">That's the same signal as ${esc(this._warning.duplicate)}. Press it again, or ${this._btn("keep", "", "keep it anyway")}</div>`
        : "";
    const actions = current
      ? [this._btn("cancel", "", "Cancel")]
      : [
          this._iconBtn("test", command.id, ICON.test, "Send it"),
          this._btn("learn-command", command.id, "Relearn"),
          this._iconBtn("delete", command.id, ICON.delete, "Delete"),
        ];
    return `<div class="row ${current ? "current" : "learned"}">
      <ha-icon class="state" icon="${current ? ICON.current : ICON.learned}"></ha-icon>
      <div class="label"><div class="name">${esc(command.name)}</div>
        <div class="hint">${current ? "Press it on your remote to learn it again" : "Learned"}</div>${warn}</div>
      ${actions.join("")}
    </div>`;
  }

  _render() {
    const root = this.shadowRoot;
    if (this._error) {
      root.innerHTML = `<style>${STYLE}</style>
        <header>${this._iconBtn("back", "", ICON.back, "Back")}<h1>Learn buttons</h1></header>
        <div class="error">${esc(this._error)}</div>`;
      this._bind();
      return;
    }
    if (!this._data) {
      root.innerHTML = `<style>${STYLE}</style><header><h1>Learn buttons</h1></header>`;
      return;
    }

    const data = this._data;
    const current = this._current();
    const learned = data.roles.filter((r) => r.learned).length + data.custom.length;
    let status;
    if (!this._unsub) {
      status = `<div class="dot off"></div><div class="text"><div class="title">Not listening</div>
        <div class="sub">${esc(this._note || "Connecting to the receiver…")}</div></div>`;
    } else if (current) {
      status = `<div class="dot"></div><div class="text">
        <div class="title">Press ${esc(this._targetLabel(current))}</div>
        <div class="sub">Point your remote at ${esc(data.receiver)}. ${this._note ? esc(this._note) : "The next button comes up by itself."}</div></div>`;
    } else {
      status = `<div class="dot idle"></div><div class="text">
        <div class="title">${learned ? "All done" : "Nothing to learn"}</div>
        <div class="sub">${esc(this._note || "Relearn a button, show a hidden one, or add your own below.")}</div></div>`;
    }

    const sections = [];
    for (const [group, label] of Object.entries(GROUPS)) {
      const roles = data.roles.filter((r) => r.group === group);
      if (!roles.length) continue;
      // Hidden buttons go to the bottom of their group
      roles.sort((a, b) => a.hidden - b.hidden);
      sections.push(
        `<div class="card"><h2>${label}</h2>${roles.map((r) => this._roleRow(r)).join("")}</div>`,
      );
    }

    const adding = current && current.name !== undefined;
    const custom = `<div class="card"><h2>${data.roles.length ? "Your own buttons" : "Buttons"}</h2>
      ${data.custom.map((c) => this._customRow(c)).join("")}
      ${
        adding
          ? `<div class="row current"><ha-icon class="state" icon="${ICON.current}"></ha-icon>
              <div class="label"><div class="name">${esc(current.name)}</div><div class="hint">Press it on your remote now</div>
              ${this._warning?.key === "new" ? `<div class="warn">That's the same signal as ${esc(this._warning.duplicate)}. Press it again, or ${this._btn("keep", "", "keep it anyway")}</div>` : ""}</div>
              ${this._btn("cancel", "", "Cancel")}</div>`
          : `<div class="add"><input id="new-name" placeholder="Name a button, for example Netflix" />
              ${this._btn("add", "", "Learn")}</div>`
      }
    </div>`;

    root.innerHTML = `<style>${STYLE}</style>
      <header>${this._iconBtn("back", "", ICON.back, "Back")}<h1>${esc(data.title)}: learn buttons</h1></header>
      <main>
        <div class="card status">${status}</div>
        ${sections.join("")}
        ${custom}
      </main>
      <footer><button class="filled-btn" data-action="done">Done</button></footer>`;
    this._bind();
  }

  _bind() {
    this.shadowRoot.querySelectorAll("[data-action]").forEach((el) =>
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._action(el.dataset.action, el.dataset.value);
      }),
    );
    const input = this.shadowRoot.querySelector("#new-name");
    if (input)
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") this._action("add", "");
      });
  }
}

customElements.define("custom-infrared-remote-panel", CustomInfraredRemotePanel);
