"""The terminal channel: queueing, merging, timeouts, and interrupts."""

import asyncio

from elifelse.channels.terminal import TerminalChannel


async def test_push_and_wait():
    ch = TerminalChannel(developer_name="Sam", agent_name="Testa")
    ch.push("hello?")
    assert ch.unread_count() == 1

    msg = await ch.wait_for_message(timeout=1)
    assert msg["content"] == "hello?"
    assert msg["sender"] == "Sam"
    assert msg["count"] == 1
    assert ch.unread_count() == 0


async def test_rapid_messages_merge_into_one_turn():
    ch = TerminalChannel()
    ch.push("are you there")
    ch.push("hello??")
    ch.push("HELLO")

    msg = await ch.wait_for_message(timeout=1)
    assert msg["content"] == "are you there\nhello??\nHELLO"
    assert msg["count"] == 3
    assert ch.unread_count() == 0


async def test_timeout_returns_none():
    ch = TerminalChannel()
    assert await ch.wait_for_message(timeout=0.01) is None


async def test_wait_picks_up_message_arriving_later():
    ch = TerminalChannel()

    async def type_soon():
        await asyncio.sleep(0.01)
        ch.push("took me a second")

    task = asyncio.create_task(type_soon())
    msg = await ch.wait_for_message(timeout=5)
    await task
    assert msg["content"] == "took me a second"


async def test_interrupt_unblocks_a_pending_wait():
    ch = TerminalChannel()
    waiter = asyncio.create_task(ch.wait_for_message(timeout=5))
    await asyncio.sleep(0)  # let the wait start
    ch.interrupt()
    assert await waiter is None

    # The interrupt flag is consumed — the channel works normally afterwards.
    ch.push("still here")
    msg = await ch.wait_for_message(timeout=1)
    assert msg["content"] == "still here"


async def test_send_prints_with_agent_name(capsys):
    ch = TerminalChannel(agent_name="Testa")
    assert await ch.send("Good morning!") is True
    assert "Testa: Good morning!" in capsys.readouterr().out
