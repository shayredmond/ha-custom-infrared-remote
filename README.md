# Custom infrared remote

[![Open your Home Assistant instance and open a repository in the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=shayredmond&repository=ha-custom-infrared-remote&category=integration)

Teach Home Assistant the buttons of any infrared remote. Each remote becomes one device, with a button entity for every command and an event entity that fires when you use the original remote.

> [!WARNING]
> This is an example integration for testing purposes. It is not production ready: expect breaking changes, and don't rely on it for anything important. Please report what you find.

## Requirements

- Home Assistant 2026.11.0 or later
- An infrared emitter entity, to send the commands
- An infrared receiver entity, to learn the commands from your remote

Home Assistant Connect IRF-2, ESPHome, Broadlink, MQTT and ZHA devices can provide these entities.

## Installation

### Marketplace

1. Open the repository in your Marketplace:

   [![Open your Home Assistant instance and open a repository in the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=shayredmond&repository=ha-custom-infrared-remote&category=integration)

   Or in the Marketplace, add `https://github.com/shayredmond/ha-custom-infrared-remote` as a custom repository of the type **Integration**.
2. Download **Custom infrared remote**.
3. Restart Home Assistant.

### Manual

1. Copy `custom_components/custom_infrared_remote` into the `custom_components` folder of your Home Assistant configuration.
2. Restart Home Assistant.

## Use

### Create a remote

1. Go to **Settings** > **Devices & services** and select **Add integration**.
2. Select **Custom infrared remote**.
3. Pick what the remote controls: **TV**, **Projector**, **Speakers or AV receiver**, **Fan**, **Blinds or curtains**, **Projector screen** or **Something else**.
4. Enter a name, for example, Living room TV, and select the infrared emitter and the infrared receiver.

### Learn buttons

For every type except **Something else**:

1. Tick the buttons your remote has. The most common ones are already ticked. Buttons you untick aren't learned, and stay unticked when you learn more later.
2. Press them on your remote when asked, one after another. As soon as a button is received, the next one comes up. If nothing arrives within 20 seconds, or a button sends the same signal as one you already pressed, the wizard stops and asks what to do.
3. When you're done, you can send a button to test it, learn a button again, add more of the suggested buttons, or add buttons with your own names.

The device then works like any other of its type: a TV, projector or speaker becomes a media player, a fan becomes a fan, and blinds or a projector screen become a cover. Buttons the device type can't use, such as Channel up, become button entities on the same device.

For **Something else**, you name each button yourself and get a list of buttons:

1. Enter the name of a button, for example, Power, and select **Next**.
2. Within 30 seconds, point your remote at the receiver and press that button.
3. Check what was received, then save it and learn the next button, or finish.

To finish, leave the button name empty and select **Next**.

### Manage buttons

Open the remote on the integration page and select **Configure**. From there you can learn new buttons, learn a button again, rename buttons, delete buttons, or change the emitter or receiver. Renaming or learning a button again keeps its entity ID, so your automations keep working.

### Use in automations

Press a button entity. To send several in a row, add a short delay between them:

```yaml
actions:
  - action: button.press
    target:
      entity_id: button.living_room_tv_power
  - delay: 0.4
  - action: button.press
    target:
      entity_id: button.living_room_tv_hdmi_1
```

### React to the original remote

The receiver keeps listening after setup. When it hears one of the learned buttons from your original remote, the **Remote button** event entity fires with the button name. Use it to trigger automations, for example to dim the lights when you press Power on the TV remote:

```yaml
triggers:
  - trigger: state
    entity_id: event.living_room_tv_remote_button
conditions:
  - condition: state
    entity_id: event.living_room_tv_remote_button
    attribute: event_type
    state: Power
actions:
  - action: light.turn_off
    target:
      area_id: living_room
```

- Holding a button fires one event, not one per repeat.
- Commands that Home Assistant sends through the same emitter are ignored for half a second, so the receiver hearing its own emitter does not count as a press.
- While you're learning buttons on that receiver, presses don't fire events.
- To stop listening, disable the **Remote button** entity in its settings.

## How it works

The receiver records the signal as a list of pulse and pause durations. The integration stores this list and sends it again through the emitter.

When you learn a button, the integration also:

- Ignores very short signals, which are usually noise.
- Recognizes NEC codes and shows their address and command.
- Removes the repeat codes that NEC remotes send while a button is held, so one press sends one command.
- Warns you when a new button sends the same signal as one you already learned.

Most receivers do not report the carrier frequency. In that case, the integration uses 38 kHz, which most consumer remotes use.

## Known limitations

- Infrared only goes one way, so on, off and the selected input are assumed from what Home Assistant last sent. If your remote has separate Power on and Power off buttons, learn those: they always work, even if the assumed state is wrong.
- Fan speed stays as Speed up and Speed down buttons, because infrared can only step the speed.
- Only NEC codes are recognized. Other codes are stored and sent as recorded.
- If your remote changes its code on every press, a learned button may only work every other time.
- Listening uses the same matching as learning, so two learned buttons that send the same code both fire.

## Feedback

Report problems and ideas in [issues](https://github.com/shayredmond/ha-custom-infrared-remote/issues). Please include the remote and the infrared device you use.

## Development

```bash
uv venv --python 3.14
uv pip install -r requirements_test.txt
uv run pytest
```
