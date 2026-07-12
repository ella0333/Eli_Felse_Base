"""InnerLife — one master toggle (inner_life.enabled) for the whole bundle:
post-activity surveys -> current emotion, relationship profiles, self-facts.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from elifelse.innerlife.profiles import ProfileManager
from elifelse.innerlife.selffacts import SelfFacts
from elifelse.innerlife.surveys import CHAT, run_survey

if TYPE_CHECKING:
    from elifelse.paths import Paths
    from elifelse.providers.base import Provider
    from elifelse.structured.registry import SchemaRegistry


class InnerLife:
    def __init__(
        self,
        provider: Provider,
        schemas: SchemaRegistry,
        paths: Paths,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.provider = provider
        self.schemas = schemas
        self.clock = clock
        self.surveys_file = paths.surveys / "surveys.jsonl"
        self.profiles = ProfileManager(paths.profiles, clock)
        self.self_facts = SelfFacts(paths.state / "self_facts.json")
        self.current_emotion = ""

    def prompt_block(self) -> str:
        return self.self_facts.prompt_block()

    async def run_survey(self, survey_type: str, subject: str, activity_key: str) -> None:
        record = await run_survey(
            self.provider, self.schemas, survey_type, subject, activity_key,
            self.surveys_file, self.clock,
        )
        if record is None:
            return
        self.current_emotion = record["emotion"]
        if survey_type == CHAT and record.get("feeling"):
            self.profiles.record_feeling(subject, record["feeling"], record["emotion"])
