# Custom infrared remote

Home Assistant custom integration "Custom infrared remote" (domain `custom_infrared_remote`; first prototyped as "Learned IR remote" with domain `learned_remote`) that learns IR commands from a physical remote and replays them. It is shared through the Marketplace (formerly HACS) for testing. It builds on the core `infrared` platform (HA 2026.11+): it consumes emitter and receiver entities and never talks to hardware itself.

## Layout

- `custom_components/custom_infrared_remote/`
  - `config_flow.py`: `LearnLoopMixin` holds the learn loop (command_name -> learn progress -> learn_done -> review menu), shared by the config flow (create remote) and the options flow (manage: learn_more, relearn, rename, delete, settings).
  - `signal.py`: `LearnedSignal` (noise filter, NEC decode, held-repeat trim, summary), `signals_match` and `find_duplicate`, `async_learn_signal`, `LearnedCommand`.
  - `remote.py`: remote entity with send, learn and delete commands by name.
  - `button.py`: one button per command. `entity.py`: shared device info and emitter binding.
  - `__init__.py`: forwards platforms, reloads on update, removes registry entries of deleted commands.
  - `translations/en.json` and `strings.json` must stay identical.
  - `brand/icon.png`: served by HA for custom integrations.
- `tests/`: pytest-homeassistant. Run with `uv run pytest`.

## Data model

One config entry is one remote. `entry.data` = emitter and receiver entity IDs. `entry.options["commands"]` = list of `{id, name, timings, modulation}`. Button unique ID = `{entry_id}_{command id}`. The command id is stable across rename and relearn. That is deliberate: it is why this uses options and not one config subentry per command (HA 2026.11 lets a device belong to one subentry only, so per-command subentries can't share a device).

## Gotchas

- ESPHome receivers (IRF-2) deliver `timings` as a protobuf `RepeatedScalarContainer`. Always copy to `list(...)` before storing, or the config entry store fails to save every entry (see `test_protobuf_timings_are_stored_as_list`).
- Frontend flow and menu titles do not get `description_placeholders`. Put placeholders in descriptions only.
- In tests, don't call `hass.async_block_till_done()` while a learn task is pending. It waits the full 30 s timeout. Use `await asyncio.sleep(0)`.
- A required multi-select preselects the first option unless it has `default=[]`.
- The rename form uses the current command names as field keys, so labels read without translations. That's fine for a custom integration but would not pass core review.

## Copy

All user-facing strings follow `~/src/NabuCasa/WRITING_STYLE.md`: no em dashes, sentence case, no emojis, no padding.

## Open questions

- Remote on/off state (currently unknown and assumed).
- Generic pulse-distance decoder for non-NEC remotes (Shay's test remote sends 21-bit codes with a ~2.2 ms leader).
- Carrier is assumed to be 38 kHz when the receiver doesn't report it.
