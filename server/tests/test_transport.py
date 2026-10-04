import asyncio
import json
import socket
import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, WSMsgType, WSServerHandshakeError

from server.cores.core_client import CoreClient
from server.main import (
    WebSocketServer,
    application,
    configure_handlers,
    is_loopback,
    origin_allowed,
    read_environment,
)
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

    def test_server_open_to_the_network_accepts_its_own_pages(self):
        self.assertTrue(origin_allowed("http://192.168.1.2:20800", "192.168.1.2:20800"))
        self.assertTrue(origin_allowed("https://Router.Example", "router.example"))
        self.assertTrue(origin_allowed("http://localhost:5173", "192.168.1.2:20800"))
        for origin, host in (
            ("https://evil.example", "192.168.1.2:20800"),
            ("http://192.168.1.2:8080", "192.168.1.2:20800"),
            ("app://192.168.1.2:20800", "192.168.1.2:20800"),
            ("null", "null"),
            ("http://192.168.1.2:20800", None),
        ):
            self.assertFalse(origin_allowed(origin, host), (origin, host))


class EnvironmentTests(unittest.TestCase):
    DATA = str(Path("data").resolve())

    def test_required_values_and_default_host(self):
        self.assertEqual(
            read_environment({"XPR_UI_PORT": "20800", "XPR_DATA_DIR": self.DATA}),
            ("0.0.0.0", 20800, Path(self.DATA)),
        )
        for host in ("127.0.0.1", "::", "localhost"):
            environ = {"XPR_UI_HOST": host, "XPR_UI_PORT": " 8080 ", "XPR_DATA_DIR": self.DATA}
            self.assertEqual(read_environment(environ), (host, 8080, Path(self.DATA)))

    def test_missing_and_invalid_values_are_named(self):
        valid = {"XPR_UI_PORT": "20800", "XPR_DATA_DIR": self.DATA}
        for changes, name in (
            ({"XPR_UI_PORT": ""}, "Set XPR_UI_PORT"),
            ({"XPR_UI_PORT": "0"}, "XPR_UI_PORT must"),
            ({"XPR_UI_PORT": "65536"}, "XPR_UI_PORT must"),
            ({"XPR_UI_PORT": "-1"}, "XPR_UI_PORT must"),
            ({"XPR_UI_PORT": "http"}, "XPR_UI_PORT must"),
            ({"XPR_DATA_DIR": " "}, "Set XPR_DATA_DIR"),
            ({"XPR_DATA_DIR": "data"}, "XPR_DATA_DIR must be an absolute path"),
            ({"XPR_UI_HOST": "router.example"}, "XPR_UI_HOST must"),
            ({"XPR_UI_HOST": "0.0.0.0:20800"}, "XPR_UI_HOST must"),
        ):
            with self.assertRaisesRegex(ValueError, name):
                read_environment(valid | changes)
        with self.assertRaises(ValueError) as raised:
            read_environment({})
        self.assertEqual(
            [line.split(",")[0] for line in str(raised.exception).splitlines()],
            ["Set XPR_UI_PORT", "Set XPR_DATA_DIR"],
        )

    def test_loopback(self):
        for host in ("127.0.0.1", "127.0.0.2", "::1", "localhost"):
            self.assertTrue(is_loopback(host), host)
        for host in ("0.0.0.0", "::", "192.168.1.2"):
            self.assertFalse(is_loopback(host), host)


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

    async def test_first_request_after_a_heartbeat(self):
        # Browsers offer compression, and their first frame is often the pong to
        # a heartbeat ping: the page sends nothing until the user acts.
        self.enterContext(patch("server.main.WEBSOCKET_HEARTBEAT", 0.2))
        async with self.session.ws_connect(self.url, compress=15) as ws:
            await self.snapshots(ws)
            # The client answers pings while it waits for a message.
            received = asyncio.create_task(self.receive(ws))
            await asyncio.sleep(0.5)
            await ws.send_json(
                {
                    "type": "change",
                    "model": "server_settings",
                    "request_id": "r1",
                    "payload": {"id": 0, "subscription_refresh_interval": 600},
                }
            )
            update, response = await received, await self.receive(ws)
            self.assertEqual(update["model"], "server_settings")
            self.assertEqual((response["request_id"], response["ok"]), ("r1", True))

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


class NetworkOriginTests(unittest.IsolatedAsyncioTestCase):
    """A page of the server opened at its address in the network may connect."""

    async def connect(self, listen: str, origin: str, host: str) -> int:
        server = WebSocketServer()
        await server.start(listen, 0)
        self.addAsyncCleanup(server.close)
        async with ClientSession() as session:
            try:
                ws = await session.ws_connect(
                    f"ws://127.0.0.1:{server.port}/ws", origin=origin, headers={"Host": host}
                )
            except WSServerHandshakeError as error:
                return error.status
            await ws.close()
            return 101

    async def test_own_page_is_accepted_only_when_open_to_the_network(self):
        page = "http://router.example:20800"
        self.assertEqual(await self.connect("0.0.0.0", page, "router.example:20800"), 101)
        with self.assertLogs("server.main", level="WARNING"):
            self.assertEqual(await self.connect("0.0.0.0", page, "evil.example:20800"), 403)
        # DNS rebinding: a site whose name now points to 127.0.0.1 looks like the server's own.
        with self.assertLogs("server.main", level="WARNING"):
            self.assertEqual(await self.connect("127.0.0.1", page, "router.example:20800"), 403)


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
