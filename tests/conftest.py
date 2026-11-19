"""Fixtures for the Custom infrared remote tests."""

import pytest
from infrared_protocols.commands.nec import NECCommand
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.components.infrared import (
    EMITTER_ENTITY_ID,
    RECEIVER_ENTITY_ID,
)

from custom_components.learned_remote.const import (
    CONF_COMMANDS,
    CONF_EMITTER,
    CONF_RECEIVER,
    DOMAIN,
)


def nec(command: int, repeats: int = 0) -> list[int]:
    """Return NEC timings for a command on address 0x04."""
    return NECCommand(
        address=0x04, command=command, repeat_count=repeats
    ).get_raw_timings()


POWER = nec(0x08)
VOL_UP = nec(0x02)
RAW = [3400, -1700, 430, -1300, 430, -430, 430, -1300, 430, -430]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A remote with two learned commands."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Living room TV",
        entry_id="tv",
        data={CONF_EMITTER: EMITTER_ENTITY_ID, CONF_RECEIVER: RECEIVER_ENTITY_ID},
        options={
            CONF_COMMANDS: [
                {"id": "p", "name": "Power", "timings": POWER, "modulation": 38000},
                {
                    "id": "v",
                    "name": "Volume up",
                    "timings": VOL_UP,
                    "modulation": 38000,
                },
            ]
        },
    )
