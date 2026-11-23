# Custom infrared remote

Home Assistant custom integration "Custom infrared remote" (domain `custom_infrared_remote`; first prototyped as "Learned IR remote" with domain `learned_remote`) that learns IR commands from a physical remote and replays them. It is an example integration for testing purposes, not production ready, shared through the Marketplace (formerly HACS). It builds on the core `infrared` platform (HA 2026.11+): it consumes emitter and receiver entities and never talks to hardware itself.

## Layout

- `custom_components/custom_infrared_remote/`
  - `config_flow.py`: `LearnLoopMixin` holds the learn loop (command_name -> learn progress -> learn_done -> review menu), shared by the config flow (create remote) and the options flow (manage: learn_more, relearn, rename, delete, settings).
  - `signal.py`: `LearnedSignal` (noise filter, NEC decode, held-repeat trim, summary), `signals_match` and `find_duplicate`, `async_learn_signal`, `LearnedCommand`.
  - `event.py`: `LearnedRemoteButtonEvent` (InfraredConsumerEntity tracking the receiver's availability + EventEntity) fires the button name for each press `presses.py` reports. Matching lives in `presses.py`: closest match wins (`find_best_match`), repeats of the same button within `REPEAT_WINDOW` collapse, matches within `ECHO_WINDOW` of any send through the remote's emitter are ignored (`async_mark_sent` before and after our sends, plus a state listener on the emitter for other integrations' sends), and nothing fires while a flow is learning on that receiver (`async_is_learning`).
  - `templates.py`: device types for the wizard (`TEMPLATES`: tv, projector, speaker, fan, blinds, screen, generic), their suggested buttons (`Role`) and which roles the main entity uses (`mapped`). Also `role_commands`, `button_commands`, `has_main_entity` for an entry.
  - `wizard.py`: `GuidedCaptureMixin`, the guided capture: `buttons` (tick list) -> `capture`/`capture_next` progress steps that auto-advance on each received signal (alternating step IDs, because a progress step followed by one with the same ID can stall the frontend) -> stops only for `capture_missed` (timeout `CAPTURE_TIMEOUT`) or `capture_duplicate` -> `ready` menu (test, relearn, more suggested, custom names via the old loop, finish). Unticked roles go to `hidden_roles` ("don't learn it"); skipped ones don't. Standard config-flow dialogs only: no images or custom frontend on main (the drawn remotes of 0.4.0b2/b3 were dropped; the learning-screen panel is the beta on the `wizard` branch). Designed with Gord on 2026-11-23: RetroArch-style controller mapping, proper device classes, a generic fallback last.
  - `presses.py`: `PressListener`, one per entry (started in `async_setup_entry`): subscribes to the receiver while it's available, filters noise/echo/learning/held repeats, and dispatches `press_signal(entry_id)` with the matched command. The event entity and the main entity (`LearnedDeviceEntity._async_heard`) both listen to it, so disabling the event entity doesn't stop state sync.
  - `media_player.py`, `fan.py`, `cover.py`: the main entity per type (`LearnedDeviceEntity` in `entity.py`), unique ID `{entry_id}_device`, assumed state. Power uses discrete on/off if learned, else toggles only when the assumed state differs.
  - `button.py`: one button per command the main entity doesn't use. `entity.py`: shared device info and emitter binding.
  - `__init__.py`: forwards platforms, reloads on update, removes registry entries of deleted commands.
  - `translations/en.json` and `strings.json` must stay identical.
  - `brand/icon.png`: served by HA for custom integrations.
- `tests/`: pytest-homeassistant. Run with `uv run pytest`.

## Data model

One config entry is one remote. `entry.data` = emitter and receiver entity IDs and `device_type` (missing on entries from before the wizard: treated as generic). `entry.options["commands"]` = list of `{id, name, timings, modulation}` plus `role` for buttons learned through the wizard. `entry.data["speed_count"]` for fans (default 3). Fan speed_up + speed_down are `mapped_together`: they become the speed slider only when both are learned. Fan and media player are not assumed_state (state follows the receiver); cover still is. `entry.options["hidden_roles"]` = suggested buttons the user chose not to learn (shared with the learning screen beta, so switching keeps them). Button unique ID = `{entry_id}_{command id}`; event entity `{entry_id}_event`. There is no remote entity: decided 2026-11-23 (v0.3.0), because its on/off controls mean nothing for IR and buttons cover sending. `_async_remove_deleted_buttons` removes the old `{entry_id}` remote entity on upgrade; don't add `remote.py` back without asking. The command id is stable across rename and relearn. That is deliberate: it is why this uses options and not one config subentry per command (HA 2026.11 lets a device belong to one subentry only, so per-command subentries can't share a device).

## Gotchas

- ESPHome receivers (IRF-2) deliver `timings` as a protobuf `RepeatedScalarContainer`. Always copy to `list(...)` before storing, or the config entry store fails to save every entry (see `test_protobuf_timings_are_stored_as_list`).
- Frontend flow and menu titles do not get `description_placeholders`. Put placeholders in descriptions only.
- In tests, don't call `hass.async_block_till_done()` while a learn task is pending. It waits the full 30 s timeout. Use `await asyncio.sleep(0)`.
- A required multi-select preselects the first option unless it has `default=[]`.
- The rename form uses the current command names as field keys, so labels read without translations. That's fine for a custom integration but would not pass core review.

## Copy

All user-facing strings follow `~/src/NabuCasa/WRITING_STYLE.md`: no em dashes, sentence case, no emojis, no padding.

## Open questions

- Generic pulse-distance decoder for non-NEC remotes (Shay's test remote sends 21-bit codes with a ~2.2 ms leader).
- Carrier is assumed to be 38 kHz when the receiver doesn't report it.
