"""Summary system: default transcript formatting, chunking, metadata, latest()."""

from datetime import datetime

import pytest

from elifelse.config import SummaryConfig
from elifelse.summary.system import SummarySystem
from fakes import FakeStore


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def summaries(mock_provider, store):
    return SummarySystem(mock_provider, store, SummaryConfig(), "Testa", "Owner",
                         clock=lambda: datetime(2026, 7, 3, 15, 30))


async def test_generate_stores_summary_with_metadata(summaries, mock_provider, store):
    mock_provider.feed({"summary": "They greeted each other."})
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello!"},
    ]

    result = await summaries.generate_and_store("chat", "Owner", messages)

    assert result == "They greeted each other."
    hits = await store.get_all("summaries")
    assert len(hits) == 1
    meta = hits[0].metadata
    assert meta["activity_type"] == "chat"
    assert meta["subject"] == "Owner"
    assert meta["date"] == "2026-07-03"
    assert meta["time"] == "03:30 PM"
    # Default formatting used the persona/owner names.
    sent = mock_provider.calls[0]["messages"][1]["content"]
    assert "Owner: hi" in sent
    assert "Testa: hello!" in sent


async def test_activity_formatter_wins_over_default(summaries, mock_provider):
    mock_provider.feed({"summary": "Custom formatted."})
    await summaries.generate_and_store(
        "game", "chess", [{"role": "user", "content": "e4"}],
        formatter=lambda msgs: "MOVES: e4",
    )
    assert mock_provider.calls[0]["messages"][1]["content"] == "MOVES: e4"


async def test_empty_transcript_returns_none(summaries, mock_provider, store):
    assert await summaries.generate_and_store("chat", "x", []) is None
    assert await store.count("summaries") == 0
    assert mock_provider.calls == []


async def test_long_transcript_chunked_then_combined(mock_provider, store):
    system = SummarySystem(mock_provider, store, SummaryConfig(chunk_chars=40),
                           "Testa", "Owner")
    long_text = ("a" * 30) + "\n" + ("b" * 30)  # two paragraphs -> two chunks
    mock_provider.feed(
        {"summary": "Part one."},
        {"summary": "Part two."},
        {"summary": "Both parts, combined."},
    )

    result = await system.generate_and_store("read", "book", [{}],
                                             formatter=lambda m: long_text)

    assert result == "Both parts, combined."
    assert len(mock_provider.calls) == 3
    combine_input = mock_provider.calls[2]["messages"][1]["content"]
    assert "Part one." in combine_input and "Part two." in combine_input


def test_chunking_rules():
    assert SummarySystem.chunk("short", 100) == ["short"]
    # Paragraph boundaries respected.
    chunks = SummarySystem.chunk("aaaa\nbbbb\ncccc", 9)
    assert chunks == ["aaaa\nbbbb", "cccc"]
    # A single oversized paragraph is hard-split.
    chunks = SummarySystem.chunk("x" * 25, 10)
    assert chunks == ["x" * 10, "x" * 10, "x" * 5]


async def test_failed_summary_returns_none(summaries, mock_provider, store):
    mock_provider.feed("garbage that is not json")
    result = await summaries.generate_and_store(
        "chat", "x", [{"role": "user", "content": "hi"}]
    )
    assert result is None
    assert await store.count("summaries") == 0


async def test_latest_returns_most_recent_filtered(summaries, store):
    await store.add("summaries", "Old chess game.",
                    {"activity_type": "game", "subject": "chess",
                     "timestamp": "2026-07-01T10:00:00"})
    await store.add("summaries", "New chess game.",
                    {"activity_type": "game", "subject": "chess",
                     "timestamp": "2026-07-02T10:00:00"})
    await store.add("summaries", "A journal entry.",
                    {"activity_type": "journal", "subject": "journal",
                     "timestamp": "2026-07-03T10:00:00"})

    assert await summaries.latest() == "A journal entry."
    assert await summaries.latest(activity_type="game") == "New chess game."
    assert await summaries.latest(activity_type="game", subject="chess") == "New chess game."
    assert await summaries.latest(activity_type="nope") is None
