"""Background memory extraction.

Messages are buffered per session; every full batch is judged by the utility
model in ONE call (which messages are worth keeping, as what). Results land in
the vector store; the foreground loop never waits for any of this — extraction
calls queue behind the provider lock like all background work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from elifelse.memory.store import MemoryStore
from elifelse.structured.validation import parse_and_validate
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.providers.base import Provider
    from elifelse.structured.registry import SchemaRegistry

FACTS = "facts"
MEMORIES = "memories"

_GAME_SYSTEM = (
    "You summarize gameplay events into concise first-person memories. "
    "Respond with only the summary text, no JSON."
)


async def summarize_game_batch(
    provider: Provider,
    store: MemoryStore,
    messages: list[dict[str, Any]],
) -> int:
    """Merge a batch of game messages into one concise gameplay memory.
    No is_fact/is_memory judgment — everything gets summarized and stored."""
    if not messages:
        return 0

    lines = []
    for msg in messages:
        role_label = "Agent" if msg["role"] == "assistant" else msg.get("source", "Game")
        lines.append(f"{role_label}: {msg['content']}")
    messages_block = "\n\n".join(lines)

    prompt = (
        "Summarize these gameplay events into one concise gameplay note "
        "in first person past tense. Focus on what happened and what matters "
        "for future play. Include specifics like locations, items, NPCs, "
        "scores, deaths, and puzzle solutions. Write 1-3 sentences.\n\n"
        f"Gameplay events:\n{messages_block}"
    )

    text = await provider.raw_completion(
        [
            {"role": "system", "content": _GAME_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    if not text or not text.strip():
        print_system("game batch summarization returned empty; batch dropped")
        return 0

    summary = text.strip().strip('"').strip()
    sample = messages[0]
    meta = {
        "source": sample.get("source", ""),
        "activity_type": sample.get("activity_type", ""),
        "timestamp": messages[-1].get("timestamp", ""),
        "keywords": ", ".join(["gameplay", sample.get("activity_type", "")]),
    }
    save_state = sample.get("save_state", "")
    if save_state:
        meta["save_state"] = save_state
    await store.add(MEMORIES, summary, meta)
    print_system("game memory stored")
    return 1

_SYSTEM = (
    "You are a memory extraction assistant. You will receive a numbered batch "
    "of conversation messages. For EACH message decide:\n"
    "- is_fact: a lasting, standalone fact worth remembering permanently "
    "(a person's preference, a real-world detail). fact_summary: the fact as "
    "one short third-person sentence ('' if not a fact).\n"
    "- is_memory: an event or exchange worth recalling later. memory_summary: "
    "one or two sentences describing what happened ('' if not).\n"
    "- keywords: 1-5 search keywords for the memory ([] if none).\n"
    "- is_goal_related: whether it relates to the agent's personal goals.\n"
    "Be selective — most messages are neither facts nor memories."
)


def build_extraction_prompt(messages: list[dict[str, Any]], rules: str) -> str:
    lines = []
    if rules:
        lines.append(f"Extraction guidance for this activity: {rules}\n")
    lines.append("Messages:")
    for i, msg in enumerate(messages):
        lines.append(f"[{i}] {msg['role']}: {msg['content']}")
    return "\n".join(lines)


async def extract_batch(
    provider: Provider,
    store: MemoryStore,
    schemas: SchemaRegistry,
    messages: list[dict[str, Any]],
    rules: str = "",
) -> int:
    """Judge one batch and store the results. Returns how many items landed."""
    if not messages:
        return 0
    schema = schemas.get("extraction_batch")
    text = await provider.raw_completion(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": build_extraction_prompt(messages, rules)},
        ],
        schema=schema,
    )
    if text is None:
        print_system("memory extraction failed (no response); batch dropped")
        return 0
    validation = parse_and_validate(text, schema)
    if not validation.ok or validation.parsed is None:
        print_system(f"memory extraction failed ({validation.reason}); batch dropped")
        return 0

    stored = 0
    for item in validation.parsed.get("results", []):
        idx = item.get("message_index", -1)
        if not isinstance(idx, int) or not (0 <= idx < len(messages)):
            continue
        src = messages[idx]
        meta = {
            "source": src.get("source", ""),
            "activity_type": src.get("activity_type", ""),
            "timestamp": src.get("timestamp", ""),
            "is_goal_related": bool(item.get("is_goal_related", False)),
        }
        if item.get("is_memory") and item.get("memory_summary"):
            keywords = item.get("keywords") or []
            await store.add(
                MEMORIES,
                str(item["memory_summary"]),
                {**meta, "keywords": ", ".join(str(k) for k in keywords)},
            )
            stored += 1
        if item.get("is_fact") and item.get("fact_summary"):
            await store.add(FACTS, str(item["fact_summary"]), meta)
            stored += 1
    return stored
