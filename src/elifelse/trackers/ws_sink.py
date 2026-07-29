"""WebSocket status broadcaster — a localhost feed for dashboards/overlays.

Enable with status.websocket_enabled in config.yaml. Every status update is
pushed as one JSON message to every connected client; no history, no auth —
it binds 127.0.0.1 only and is meant for same-machine consumers.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from websockets.asyncio.server import serve

from elifelse.textutils import print_system


class WebSocketSink:
    """A StatusTracker sink: call it with the status payload to broadcast."""

    def __init__(self, port: int = 8765) -> None:
        self.port = port  # 0 = pick a free port (tests); updated after start()
        self._clients: set[Any] = set()
        self._server: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._server = await serve(self._handler, "127.0.0.1", self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        print_system(f"status websocket listening on ws://127.0.0.1:{self.port}")

    async def _handler(self, ws: Any) -> None:
        self._clients.add(ws)
        try:
            await ws.wait_closed()
        finally:
            self._clients.discard(ws)

    def __call__(self, payload: dict[str, Any]) -> None:
        """Broadcast one status payload to all connected clients."""
        if self._loop is None or not self._clients:
            return
        message = json.dumps(payload, default=str)
        for ws in list(self._clients):
            self._loop.create_task(self._send(ws, message))

    async def _send(self, ws: Any, message: str) -> None:
        try:
            await ws.send(message)
        except Exception:
            self._clients.discard(ws)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._clients.clear()
