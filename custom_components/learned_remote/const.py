"""Constants for the Custom infrared remote integration."""

from typing import Final

DOMAIN: Final = "learned_remote"

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
