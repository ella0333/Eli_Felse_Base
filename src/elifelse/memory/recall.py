"""Two-tier recall.

Tier 1: memories from the SAME source (plus 'self') at a permissive
        similarity bar — personal, context-specific.
Tier 2: if there's room left, anything from anywhere at a stricter bar —
        cross-context associations.

After similarity filtering, results are sorted by recency (most recent
first) so the freshest relevant memories win when there are ties.
Memories still visible in the context window are excluded to avoid
redundant injection.
"""

from __future__ import annotations

from elifelse.config import MemoryConfig
from elifelse.memory.store import MemoryHit, MemoryStore

MEMORIES = "memories"

# Fetch more than max_recall from ChromaDB so post-filtering has a good pool.
_QUERY_POOL = 10


async def two_tier_recall(
    store: MemoryStore,
    query: str,
    source: str,
    config: MemoryConfig,
    context_horizon: str | None = None,
) -> list[str]:
    hits: list[MemoryHit] = []
    seen_ids: set[str] = set()

    # Tier 1: source-specific + self, permissive threshold.
    direct = await store.query(
        MEMORIES, query, n=_QUERY_POOL,
        where={"$or": [{"source": source}, {"source": "self"}]},
    )
    for hit in direct:
        if hit.similarity >= config.direct_threshold:
            hits.append(hit)
            seen_ids.add(hit.id)

    # Tier 2: global, stricter threshold.
    if len(hits) < config.max_recall:
        broad = await store.query(MEMORIES, query, n=_QUERY_POOL)
        for hit in broad:
            if hit.id in seen_ids:
                continue
            if hit.similarity >= config.global_threshold:
                hits.append(hit)
                seen_ids.add(hit.id)

    # Filter out memories still visible in the context window.
    if context_horizon:
        hits = [h for h in hits if h.metadata.get("timestamp", "") < context_horizon]

    # Sort by recency (most recent first), then cap.
    hits.sort(key=lambda h: h.metadata.get("timestamp", ""), reverse=True)
    return [h.text for h in hits[: config.max_recall]]
