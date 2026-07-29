"""'/' terminal commands drive ControlState; plain text still reaches the agent."""

import asyncio

from elifelse.channels.terminal import TerminalChannel
from elifelse.loop.control import make_command_handler


def _channel(app) -> TerminalChannel:
    channel = TerminalChannel(command_handler=make_command_handler(app))
    app.channels["terminal"] = channel
    return channel


async def test_stop_command_not_queued(app):
    channel = _channel(app)
    channel.push("/stop")
    assert app.control.stop_requested
    assert channel.unread_count() == 0  # commands never become chat messages


async def test_pause_and_resume(app):
    channel = _channel(app)
    channel.push("/pause")
    assert app.control.pause_requested
    channel.push("/resume")
    assert not app.control.pause_requested


async def test_plain_text_is_queued(app):
    channel = _channel(app)
    channel.push("hello there")
    assert channel.unread_count() == 1
    assert not app.control.stop_requested


async def test_unknown_command_swallowed_with_hint(app, capsys):
    channel = _channel(app)
    channel.push("/dance")
    assert channel.unread_count() == 0
    assert "/help" in capsys.readouterr().out


async def test_stop_interrupts_pending_chat_wait(app):
    """/stop while the agent is waiting for a chat reply unblocks the wait."""
    channel = _channel(app)
    task = asyncio.create_task(channel.wait_for_message(timeout=5))
    await asyncio.sleep(0.01)
    channel.push("/stop")
    assert await asyncio.wait_for(task, timeout=1) is None
    assert app.control.stop_requested
