"""Constants for the Custom infrared remote integration."""

from typing import Final

DOMAIN: Final = "custom_infrared_remote"

CONF_EMITTER: Final = "emitter_entity_id"
CONF_RECEIVER: Final = "receiver_entity_id"
CONF_COMMANDS: Final = "commands"

# Keys inside a stored command
CMD_ID: Final = "id"
CMD_NAME: Final = "name"
CMD_TIMINGS: Final = "timings"
CMD_MODULATION: Final = "modulation"

LEARN_TIMEOUT: Final = 30

# Most receivers demodulate the signal and do not report the carrier.
# 38 kHz is the carrier that most consumer remotes use.
DEFAULT_MODULATION: Final = 38000

# Signals shorter than this are treated as noise (stray IR, sunlight, CFL flicker)
MIN_TIMINGS: Final = 8

# Ignore matches this long after sending through the remote's emitter, so the
# receiver hearing our own transmission does not look like a button press
ECHO_WINDOW: Final = 0.5

# Presses of the same button closer together than this count as one (held button)
REPEAT_WINDOW: Final = 0.3

# Which device type the wizard set up (see templates.py); missing means generic
CONF_DEVICE_TYPE: Final = "device_type"

# Optional key on a stored command: the wizard role it fills, such as "power"
CMD_ROLE: Final = "role"

# How long the guided capture waits for each button before asking what to do
CAPTURE_TIMEOUT: Final = 20

# Suggested buttons the user chose not to learn ("don't learn it")
CONF_HIDDEN_ROLES: Final = "hidden_roles"

# Fans: how many speed steps the speed up and speed down buttons go through
CONF_SPEED_COUNT: Final = "speed_count"
DEFAULT_SPEED_COUNT: Final = 3

# Pause between repeated presses, so the device sees each one
STEP_DELAY: Final = 0.3
