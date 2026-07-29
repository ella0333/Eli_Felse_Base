"""Memory system on a FakeStore: batching, extraction, two-tier recall,
consolidation, trim force-flush, and full lifecycle wiring."""

from datetime import datetime

import pytest

from elifelse.memory.system import MemorySystem
from elifelse.structured.registry import SchemaRegistry
from fakes import FakeStore


def _verdict(index, fact="", memory="", keywords=(), goal=False):
    return {
        "message_index": index,
        "is_fact": bool(fact),
        "fact_summary": fact,
        "is_memory": bool(memory),
        "memory_summary": memory,
        "keywords": list(keywords),
        "is_goal_related": goal,
    }


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def memory(config, mock_provider, store):
    return MemorySystem(mock_provider, store, config.memory, SchemaRegistry())


async def test_full_batch_triggers_background_extraction(memory, mock_provider, store):
    mock_provider.feed(
        {"results": [
            _verdict(0, fact="The owner drinks tea every morning."),
            _verdict(3, memory="They planned the garden together.", keywords=["garden"]),
        ]}
    )
    for i in range(memory.config.batch_size):  # 6 -> exactly one batch
        memory.push_message("chat", "user", f"message {i}",
                            source="owner", activity_type="chat")
    await memory.wait_idle()

    assert await store.count("facts") == 1
    memories = await store.get_all("memories")
    assert len(memories) == 1
    assert memories[0].text == "They planned the garden together."
    assert memories[0].metadata["source"] == "owner"
    assert memories[0].metadata["keywords"] == "garden"
    assert memory.buffers["chat"] == []  # batch consumed


async def test_flush_remaining_extracts_leftovers(memory, mock_provider, store):
    mock_provider.feed({"results": [_verdict(0, memory="A short chat happened.")]})
    memory.push_message("journal", "assistant", "just one message", source="journal")

    await memory.flush_remaining("journal")

    assert await store.count("memories") == 1
    assert "journal" not in memory.buffers


async def test_invalid_extraction_response_drops_batch_safely(memory, mock_provider, store):
    mock_provider.feed("not json", "still not json", "nope")  # 3 raw retries
    memory.push_message("chat", "user", "hello", source="owner")
    await memory.flush_remaining("chat")
    assert await store.count("memories") == 0
    assert await store.count("facts") == 0


async def test_two_tier_recall(memory, store):
    q = "painting sunsets beach today"
    # Tier 1: source match, sim 1.0, older
    await store.add("memories", "painting sunsets beach today was lovely",
                    {"source": "journal", "timestamp": "2026-01-01T12:00:00"})
    # Tier 2: different source, sim 1.0 (all query words), newer
    await store.add("memories", "painting sunsets beach today discussion",
                    {"source": "chat", "timestamp": "2026-01-02T12:00:00"})
    # Excluded: sim 0.25, below both thresholds
    await store.add("memories", "painting supplies restocked",
                    {"source": "chat", "timestamp": "2026-01-03T12:00:00"})

    results = await memory.recall(q, source="journal")

    # Both pass thresholds; sorted by recency (newest first)
    assert results == [
        "painting sunsets beach today discussion",
        "painting sunsets beach today was lovely",
    ]


async def test_recall_caps_results(memory, store):
    for i in range(5):
        await store.add("memories", f"painting sunsets beach today number{i}",
                        {"source": "journal", "timestamp": f"2026-01-0{i + 1}T12:00:00"})
    results = await memory.recall("painting sunsets beach today", source="journal")
    assert len(results) == memory.config.max_recall == 3


async def test_recall_excludes_context_visible(memory, mock_provider, store):
    """Memories from messages still in the context window are not re-injected."""
    # Put something in context so oldest_timestamp() returns a value.
    mock_provider.context.add("user", "some visible context")

    # This memory predates the context window -- should be recalled.
    await store.add("memories", "painting sunsets beach today old",
                    {"source": "journal", "timestamp": "2020-01-01T12:00:00"})
    # This memory is from within / after the context window -- excluded.
    await store.add("memories", "painting sunsets beach today recent",
                    {"source": "journal", "timestamp": "2099-01-01T12:00:00"})

    results = await memory.recall("painting sunsets beach today", source="journal")
    assert len(results) == 1
    assert "old" in results[0]


async def test_consolidation_applies_keep_update_remove(memory, mock_provider, store):
    memory.config.max_facts = 3
    for text in ["Fact one.", "Fact two.", "Fact three.", "Fact four."]:
        await store.add("facts", text)
    mock_provider.feed(
        {"facts": [
            {"action": "keep", "fact": "Fact one."},
            {"action": "remove", "fact": "Fact two."},
            {"action": "update", "fact": "Facts three and four, merged."},
            {"action": "remove", "fact": "Fact four."},
        ]}
    )

    await memory.consolidate()

    texts = [h.text for h in await store.get_all("facts")]
    assert texts == ["Fact one.", "Facts three and four, merged."]
    assert await memory.get_facts() == texts


async def test_context_trim_forces_flush(memory, mock_provider, store):
    # Buffered messages get an old clock...
    memory.clock = lambda: datetime(2020, 1, 1, 12, 0, 0)
    memory.push_message("chat", "user", "ancient message", source="owner")
    # ...then the model context moves on past them (real 'now' timestamps).
    mock_provider.context.add("user", "much newer context")

    mock_provider.feed({"results": [_verdict(0, memory="An ancient exchange.")]})
    memory.push_message("chat", "user", "another old message", source="owner")
    await memory.wait_idle()

    assert await store.count("memories") == 1
    assert memory.buffers["chat"] == []


async def test_lifecycle_wiring_summary_then_extraction(app, mock_provider, store):
    """Full run_activity with memory + summaries on the FakeStore: the summary
    is generated from the activity's messages, extraction flushes after."""
    from elifelse.loop.lifecycle import run_activity
    from elifelse.summary.system import SummarySystem

    app.memory = MemorySystem(mock_provider, store, app.config.memory, app.schemas)
    app.summaries = SummarySystem(mock_provider, store, app.config.summary,
                                  app.persona.name, app.config.developer_name)
    app.registry.load_builtins()

    mock_provider.feed(
        {"thinking": "t", "entry": "Dear diary, the garden is blooming."},   # journal
        {"summary": "Wrote a journal entry about the garden."},              # summary
        {"results": [_verdict(0, memory="The garden is blooming.")]},        # extraction
    )
    await run_activity(app, app.registry.get("journal"))

    assert await store.count("summaries") == 1
    assert await app.summaries.latest(activity_type="journal") == (
        "Wrote a journal entry about the garden."
    )
    assert await store.count("memories") == 1
