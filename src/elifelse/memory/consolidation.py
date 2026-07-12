"""Fact consolidation — keeps the permanent fact list small and current.

When the fact count passes the cap, the utility model reviews the whole list
in one call and returns keep/update/remove per fact (position-aligned with
the input list). Runs in the background; also a good sleep-time job.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elifelse.memory.store import MemoryStore
from elifelse.structured.validation import parse_and_validate
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.providers.base import Provider
    from elifelse.structured.registry import SchemaRegistry

FACTS = "facts"

_SYSTEM = (
    "You maintain a compact list of permanent facts. Review the numbered list; "
    "for EACH fact (in the same order) answer with an action:\n"
    "- keep: still true and worth keeping (repeat the fact unchanged)\n"
    "- update: still relevant but should be merged/reworded (give the new wording)\n"
    "- remove: outdated, duplicated, or trivial (repeat the fact)\n"
    "Prefer merging near-duplicates via update+remove. Answer with exactly one "
    "entry per input fact, in the same order."
)


async def consolidate_facts(
    provider: Provider,
    store: MemoryStore,
    schemas: SchemaRegistry,
    max_facts: int,
) -> None:
    hits = await store.get_all(FACTS)
    if len(hits) <= max_facts:
        return
    schema = schemas.get("fact_consolidation")
    listing = "\n".join(f"[{i}] {h.text}" for i, h in enumerate(hits))
    text = await provider.raw_completion(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Facts ({len(hits)}, cap {max_facts}):\n{listing}"},
        ],
        schema=schema,
    )
    if text is None:
        return
    validation = parse_and_validate(text, schema)
    if not validation.ok or validation.parsed is None:
        print_system(f"fact consolidation failed ({validation.reason}); keeping all facts")
        return

    actions = validation.parsed.get("facts", [])
    removed = updated = 0
    for i, item in enumerate(actions):
        if i >= len(hits):
            break
        action = item.get("action")
        if action == "remove":
            await store.delete(FACTS, [hits[i].id])
            removed += 1
        elif action == "update" and item.get("fact"):
            await store.delete(FACTS, [hits[i].id])
            await store.add(FACTS, str(item["fact"]), hits[i].metadata)
            updated += 1
    print_system(f"facts consolidated: {removed} removed, {updated} updated")
