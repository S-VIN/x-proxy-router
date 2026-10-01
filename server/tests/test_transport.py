import asyncio
import json
import socket
import unittest
from contextlib import chdir
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, WSMsgType, WSServerHandshakeError

from server.cores.core_client import CoreClient
from server.main import WebSocketServer, application, configure_handlers, origin_allowed
from server.models.application_context import ApplicationContext
from server.tests.support import startup_finished


class OriginTests(unittest.TestCase):
    def test_only_local_pages_and_non_browsers(self):
        for origin in (
            None,
            "http://localhost:5173",
            "https://localhost",
            "http://127.0.0.1:8080",
            "http://[::1]:3000",
        ):
            self.assertTrue(origin_allowed(origin), origin)
        for origin in (
            "https://evil.example",
            "http://localhost.evil.example",
            "null",
            "file://",
            "app://x-proxy-router",
            "",
        ):
            self.assertFalse(origin_allowed(origin), origin)
        with patch("server.main.WEBSOCKET_ALLOWED_ORIGINS", frozenset({"app://x-proxy-router"})):
            self.assertTrue(origin_allowed("app://x-proxy-router"))


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        core = AsyncMock(spec=CoreClient)
        self.enterContext(patch("server.main.MihomoClient", return_value=core))
        self.enterContext(
            patch(
                "server.handlers.subscriptions.load_subscription",
                new_callable=AsyncMock,
                return_value=[],
            )
        )
        self.manager = application()
        self.context: ApplicationContext = await self.manager.__aenter__()
        self.closed = False
        configure_handlers(self.context)
        await startup_finished(self.context)
        self.session = await self.enterAsyncContext(ClientSession())

    async def asyncTearDown(self):
        if not self.closed:
            await self.manager.__aexit__(None, None, None)

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.context.websocket.port}/ws"

    async def receive(self, ws) -> dict:
        async with asyncio.timeout(2):
            return await ws.receive_json()

    async def snapshots(self, ws) -> list[dict]:
        return [await self.receive(ws) for _ in range(8)]

    async def test_snapshot_request_and_response_over_the_network(self):
        async with self.session.ws_connect(self.url) as ws:
            snapshots = await self.snapshots(ws)
            self.assertEqual(
                [(m["type"], m["model"], m["refresh"]) for m in snapshots],
                [
                    ("subscription", "server_settings", True),
                    ("subscription", "subscription_link", True),
                    ("subscription", "reg_filter", True),
                    ("subscription", "outbound_test", True),
                    ("subscription", "outbound_server", True),
                    ("subscription", "inbound_server", True),
                    ("subscription", "routing_rule", True),
                    ("subscription", "task", True),
                ],
            )
            await ws.send_str(
                json.dumps(
                    {
                        "type": "change",
                        "model": "server_settings",
                        "request_id": "r1",
                        "payload": {"id": 0, "subscription_refresh_interval": 600},
                    }
                )
            )
            update, response = await self.receive(ws), await self.receive(ws)
            self.assertEqual(update["payload"][0]["subscription_refresh_interval"], 600)
            self.assertEqual(
                response,
                {
                    "type": "response",
                    "model": "server_settings",
                    "request_id": "r1",
                    "ok": True,
                    "payload": {},
                },
            )
            await ws.send_str("not json")
            error = await self.receive(ws)
            self.assertEqual((error["request_id"], error["error"]["code"]), (None, "bad_request"))

    async def test_changes_reach_other_clients(self):
        async with (
            self.session.ws_connect(self.url) as first,
            self.session.ws_connect(self.url, origin="http://localhost:5173") as second,
        ):
            await self.snapshots(first)
            await self.snapshots(second)
            await first.send_json(
                {
                    "type": "change",
                    "model": "server_settings",
                    "request_id": "r1",
                    "payload": {"id": 0, "subscription_refresh_interval": 60},
                }
            )
            update = await self.receive(second)
            self.assertEqual(update["model"], "server_settings")
            self.assertEqual(update["payload"][0]["subscription_refresh_interval"], 60)

    async def test_foreign_origin_is_rejected(self):
        with (
            self.assertLogs("server.main", level="WARNING"),
            self.assertRaises(WSServerHandshakeError) as raised,
        ):
            await self.session.ws_connect(self.url, origin="https://evil.example")
        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(self.context.websocket._connections, {})

    async def test_binary_frames_close_the_connection(self):
        async with self.session.ws_connect(self.url) as ws:
            await self.snapshots(ws)
            await ws.send_bytes(b"{}")
            async with asyncio.timeout(2):
                message = await ws.receive()
            self.assertEqual(message.type, WSMsgType.CLOSE)
            self.assertEqual(message.data, 1003)

    async def test_client_disconnect_removes_the_connection(self):
        async with self.session.ws_connect(self.url) as ws:
            await self.snapshots(ws)
            self.assertEqual(len(self.context.websocket._connections), 1)
        async with asyncio.timeout(2):
            while self.context.websocket._connections:
                await asyncio.sleep(0.01)

    async def test_shutdown_closes_clients_and_releases_the_port(self):
        port = self.context.websocket.port
        assert port is not None
        async with self.session.ws_connect(self.url) as ws:
            await self.snapshots(ws)
            closing = asyncio.create_task(self.manager.__aexit__(None, None, None))
            self.closed = True
            async with asyncio.timeout(5):
                message = await ws.receive()
                await closing
            self.assertEqual(message.type, WSMsgType.CLOSE)
            self.assertEqual(message.data, 1001)
        self.assertIsNone(self.context.websocket.port)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))

    async def test_second_start_is_rejected(self):
        with self.assertRaises(RuntimeError):
            await self.context.websocket.start("127.0.0.1", 0)


class PortTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_port_fails_and_stop_is_idempotent(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            server = WebSocketServer()
            with self.assertRaises(OSError):
                await server.start("127.0.0.1", busy.getsockname()[1])
        self.assertIsNone(server.port)
        await server.stop()
        await server.close()
