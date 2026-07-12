"""Built-in activities. Reference-quality on purpose, each one demonstrates a
piece of the module API (see docs/developing-modules.md):

- journal:     the minimal complete activity (free text + store + remember)
- ponder:      the multi-turn loop-until-return_to_menu pattern
- eat:         custom schemas, daily limits, per-activity storage
- nap:         delegating to a framework subsystem (the day cycle)
- chat:        channels, subjects, and the chat survey
- environment: driving another subsystem from a constrained choice

Journal stays first: with the mock provider in auto mode, menu option 'A' is
what gets picked, so a fresh `elifelse run --provider mock` demo journals.
"""

from elifelse.activities.builtin.chat import ChatActivity
from elifelse.activities.builtin.eat import EatActivity
from elifelse.activities.builtin.environment import EnvironmentActivity
from elifelse.activities.builtin.journal import JournalActivity
from elifelse.activities.builtin.nap import NapActivity
from elifelse.activities.builtin.ponder import PonderActivity

BUILTIN_ACTIVITIES = [
    JournalActivity,
    PonderActivity,
    EatActivity,
    NapActivity,
    ChatActivity,
    EnvironmentActivity,
]

__all__ = [
    "BUILTIN_ACTIVITIES",
    "ChatActivity",
    "EatActivity",
    "EnvironmentActivity",
    "JournalActivity",
    "NapActivity",
    "PonderActivity",
]
