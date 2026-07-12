"""Graceful pause/stop — the clean alternative to Ctrl+C.

The owner requests pause/stop (terminal command or programmatically); the base
finishes the current activity, runs the normal post-activity lifecycle, saves,
then idles (pause) or exits cleanly (stop). Ctrl+C still works and still falls
into crash recovery — this just makes the clean path exist.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.app import App


class ControlState:
    def __init__(self) -> None:
        self._pause_requested = False
        self._stop_requested = False
        self._resume_event = asyncio.Event()

    def request_pause(self) -> None:
        self._pause_requested = True
        self._resume_event.clear()

    def request_stop(self) -> None:
        self._stop_requested = True
        self._resume_event.set()  # a paused loop should exit promptly too

    def resume(self) -> None:
        self._pause_requested = False
        self._resume_event.set()

    @property
    def pause_requested(self) -> bool:
        return self._pause_requested

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    async def wait_for_resume(self) -> None:
        await self._resume_event.wait()
        self._resume_event.clear()


def make_command_handler(app: App) -> Callable[[str], bool]:
    """Terminal '/' commands. Returns True if the line was a command (i.e. it
    should NOT be queued as a chat message for the agent)."""

    def handle(text: str) -> bool:
        cmd = text.strip().lower()
        if cmd == "/pause":
            app.control.request_pause()
            print_system("pausing after the current activity finishes...")
        elif cmd == "/resume":
            app.control.resume()
        elif cmd in ("/stop", "/exit", "/quit"):
            app.control.request_stop()
            print_system("stopping after the current activity finishes...")
            for channel in app.channels.values():
                try:
                    channel.interrupt()  # unblock any pending wait_for_message
                except Exception:
                    pass
        elif cmd.startswith("/message"):
            msg = text.strip()[len("/message"):].strip()
            if not msg:
                print_system("usage: /message <your message>")
            else:
                channel = app.channels.get("terminal")
                if channel is not None:
                    channel.queue_direct(msg)
                    print_system("message sent (the agent will see it at the next menu)")
                else:
                    print_system("terminal channel not ready yet")
        elif cmd == "/dashboard":
            if app._dashboard is not None:
                print_system(f"dashboard already running on http://127.0.0.1:{app.config.dashboard.port}")
            else:
                try:
                    from elifelse.dashboard import Dashboard

                    app._dashboard = Dashboard(app, app.config.dashboard.port)
                    app._dashboard.start()
                except Exception as e:
                    print_system(f"failed to start dashboard: {e}")
        elif cmd == "/help":
            print_system(
                "commands: /message <text>  /pause  /resume  /stop  /dashboard  /help"
            )
        else:
            print_system(f"unknown command '{text}' — try /help")
        return True  # every '/' line is treated as a command, never chat text

    return handle
