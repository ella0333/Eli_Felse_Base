"""The WebSocket status sink: a real client connects and receives status JSON."""

import asyncio
import json

from websockets.asyncio.client import connect

from elifelse.app import App
from elifelse.trackers.ws_sink import WebSocketSink


async def _wait_for_client(sink: WebSocketSink) -> None:
    for _ in range(200):
        if sink._clients:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("client never registered with the sink")


async def test_ws_sink_broadcasts():
    sink = WebSocketSink(port=0)  # 0 = pick a free port
    await sink.start()
    try:
        async with connect(f"ws://127.0.0.1:{sink.port}") as ws:
            await _wait_for_client(sink)
            sink({"type": "status_update", "activity": "journaling"})
            data = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            assert data["activity"] == "journaling"
    finally:
        await sink.stop()


async def test_app_wires_ws_sink(config, persona, mock_provider):
    config.status.websocket_enabled = True
    config.status.websocket_port = 0
    app = App(config, persona, provider=mock_provider)
    await app.startup(discover=False)
    try:
        async with connect(f"ws://127.0.0.1:{app._ws_sink.port}") as ws:
            await _wait_for_client(app._ws_sink)
            app.status.set_activity("pondering")
            data = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            assert data["activity"] == "pondering"
            assert data["type"] == "status_update"
    finally:
        await app.shutdown()
