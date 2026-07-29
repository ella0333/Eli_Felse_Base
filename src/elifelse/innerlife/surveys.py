"""Post-activity surveys.

Activities declare survey = "simple" (how are you feeling?) or "chat"
(feelings + a feeling-about-this-person enum that updates their profile).
Results are appended to data/surveys/surveys.jsonl. A failed survey is
skipped, never fatal.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from elifelse.providers.base import Provider
    from elifelse.structured.registry import SchemaRegistry

SIMPLE = "simple"
CHAT = "chat"


def _prompt(survey_type: str, subject: str) -> str:
    if survey_type == CHAT:
        return (
            f"[You just finished talking with {subject}. Take a moment: how are "
            f"you feeling right now, and how do you feel about {subject}? "
            "Pick ONE word for your emotion.]"
        )
    return (
        f"[You just finished {subject}. Take a moment: how are you feeling "
        "right now? Pick ONE word for your emotion.]"
    )


async def run_survey(
    provider: Provider,
    schemas: SchemaRegistry,
    survey_type: str,
    subject: str,
    activity_key: str,
    surveys_file: Path,
    clock: Callable[[], datetime] = datetime.now,
) -> dict[str, Any] | None:
    """Ask, record, and return {'emotion': ..., 'feeling'?: ...} or None."""
    schema_name = "survey_chat" if survey_type == CHAT else "survey_simple"
    result = await provider.generate(_prompt(survey_type, subject), schema=schemas.get(schema_name))
    if "error" in result or not result.get("emotion"):
        return None

    # Terminal visibility — show what the survey produced.
    if result.get("thinking"):
        print(f"\nThinking: {result['thinking']}")
    print(f"Feeling: {result['emotion']}")
    if result.get("feeling"):
        print(f"About {subject}: {result['feeling']}")

    record: dict[str, Any] = {
        "time": clock().isoformat(),
        "activity": activity_key,
        "subject": subject,
        "type": survey_type,
        "emotion": result["emotion"],
    }
    if result.get("feeling"):
        record["feeling"] = result["feeling"]

    surveys_file.parent.mkdir(parents=True, exist_ok=True)
    with surveys_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record
