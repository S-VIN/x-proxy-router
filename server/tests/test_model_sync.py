import asyncio
import json
import unittest
from contextlib import chdir
from dataclasses import replace
from datetime import UTC, datetime
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from uuid import UUID

from server.cores.core_client import CoreClient
from server.main import WebSocketServer, application
from server.model_sync import ModelChannel, ModelSync
from server.models import (
    FilterReason,
    OutboundProtocol,
    OutboundServer,
    OutboundTest,
    OutboundTestRule,
    RegFilter,
    ServerSettings,
    ShadowsocksMethod,
    SubscriptionLink,
    UotVersion,
    VlessFlow,
    serialize,
)
from server.tests.support import startup_finished


def vless(**changes) -> OutboundServer:
    return replace(
        OutboundServer(
            id="vless",
            name="VLESS",
            address="example.com",
            port=443,
            protocol=OutboundProtocol.VLESS,
            vless_uuid=UUID(int=1),
            vless_flow=VlessFlow.VISION,
            alpn=("h2",),
            stream_options={"hysteriaSettings": {"auth": "secret"}},
            extra_params={"token": "secret"},
        ),
        **changes,
    )


class OutboundServerTests(unittest.TestCase):
    def test_active_protocol_defaults_and_other_protocols_unset(self):
        server = vless()
        self.assertEqual(server.vless_encryption, "none")
        self.assertEqual(server.vless_extra, {})
        self.assertIsNone(server.shadowsocks_method)
        self.assertIsNone(server.hysteria_version)
        hysteria = OutboundServer(
            name="h",
            address="example.com",
            port=443,
            protocol=OutboundProtocol.HYSTERIA,
            hysteria_auth="auth",
        )
        self.assertEqual(hysteria.hysteria_version, 2)
        self.assertIsNone(hysteria.vless_flow)

    def test_rejects_missing_and_foreign_protocol_fields(self):
        with self.assertRaisesRegex(ValueError, "shadowsocks_method is required"):
            OutboundServer(
                name="s",
                address="example.com",
                port=443,
                protocol=OutboundProtocol.SHADOWSOCKS,
                shadowsocks_password="p",
            )
        with self.assertRaisesRegex(ValueError, "hysteria_auth does not apply"):
            vless(hysteria_auth="auth")

    def test_secrets_are_hidden_from_repr(self):
        self.assertNotIn(str(UUID(int=1)), repr(vless()))
        self.assertNotIn("secret", repr(vless()))


class RegFilterTests(unittest.TestCase):
    def test_found_anywhere_in_the_name_and_case_sensitive(self):
        reg_filter = RegFilter(reg="RU|Россия")
        self.assertTrue(reg_filter.matches("🇷🇺 RU Moscow"))
        self.assertTrue(reg_filter.matches("Россия 2"))
        self.assertFalse(reg_filter.matches("Peru"))
        self.assertTrue(RegFilter(reg="(?i)ru").matches("Peru"))
        self.assertFalse(RegFilter(reg="^NL$").matches("NL 2"))

    def test_invalid_filters_are_rejected(self):
        for reg in ("", "(", "[a-"):
            with self.subTest(reg=reg), self.assertRaises(ValueError):
                RegFilter(reg=reg)
        with self.assertRaises(ValueError):
            RegFilter(reg="RU", id="")


class SerializationTests(unittest.TestCase):
    def test_flat_server_without_secrets(self):
        data = serialize(vless())
        self.assertEqual(json.loads(json.dumps(data)), data)
        assert isinstance(data, dict)
        self.assertEqual(data["protocol"], "vless")
        self.assertEqual(data["vless_flow"], "xtls-rprx-vision")
        self.assertIs(type(data["vless_flow"]), str)
        self.assertEqual(data["alpn"], ["h2"])
        self.assertIsNone(data["shadowsocks_method"])
        for name in (
            "vless_uuid",
            "vless_encryption",
            "vless_extra",
            "stream_options",
            "extra_params",
            "shadowsocks_password",
            "shadowsocks_extra",
            "hysteria_auth",
            "hysteria_extra",
        ):
            self.assertNotIn(name, data)
        self.assertNotIn("secret", json.dumps(data))

    def test_int_enum_and_subscription_link(self):
        server = OutboundServer(
            name="s",
            address="example.com",
            port=443,
            protocol=OutboundProtocol.SHADOWSOCKS,
            shadowsocks_password="p",
            shadowsocks_method=ShadowsocksMethod.AES_128_GCM,
            shadowsocks_uot_version=UotVersion.V2,
        )
        data = serialize(server)
        assert isinstance(data, dict)
        self.assertIs(type(data["shadowsocks_uot_version"]), int)
        link = SubscriptionLink(url="https://example.com/token", id="link")
        self.assertEqual(serialize(link), {"id": "link", "url_short": "https://example.com"})

    def test_server_settings_datetime_in_utc(self):
        settings = ServerSettings(
            subscription_refresh_interval=60,
            last_subscription_refresh=datetime(2026, 9, 26, 12, tzinfo=UTC),
        )
        self.assertEqual(
            serialize(settings),
            {
                "id": 0,
                "subscription_refresh_interval": 60,
                "last_subscription_refresh": "2026-09-26T12:00:00Z",
                "outbound_tests": [],
            },
        )
        with self.assertRaises(ValueError):
            serialize(datetime(2026, 9, 26))  # noqa: DTZ001 - naive on purpose

    def test_outbound_tests_and_server_health(self):
        test = OutboundTest(
            url="https://www.gstatic.com/generate_204",
            alias="google",
            rule=OutboundTestRule.STATUS_204,
        )
        data = serialize(ServerSettings(outbound_tests=(test,)))
        assert isinstance(data, dict)
        self.assertEqual(
            data["outbound_tests"],
            [
                {
                    "url": "https://www.gstatic.com/generate_204",
                    "alias": "google",
                    "rule": "status_204",
                }
            ],
        )
        unchecked = serialize(vless())
        assert isinstance(unchecked, dict)
        self.assertEqual(
            [unchecked[name] for name in ("ping", "speed", "rating", "tests")], [None] * 4
        )
        self.assertIsNone(unchecked["filtered"])
        checked = serialize(vless(ping=40, speed=1000, rating=9, tests={"google": False}))
        assert isinstance(checked, dict)
        self.assertEqual(
            [checked[name] for name in ("ping", "speed", "rating", "tests")],
            [40, 1000, 9, {"google": False}],
        )

    def test_filter_reason_and_reg_filter(self):
        data = serialize(vless(filtered=FilterReason.BY_PING))
        assert isinstance(data, dict)
        self.assertEqual(data["filtered"], "by_ping")
        self.assertEqual(serialize(RegFilter(id="f", reg="^RU")), {"id": "f", "reg": "^RU"})


class Client:
    """Records frames the way a transport would receive them."""

    def __init__(self, websocket: WebSocketServer, connection_id: str = "client"):
        self.frames: list[dict] = []
        self.received = asyncio.Event()
        websocket.connect(connection_id, self._send)

    async def _send(self, frame: str) -> None:
        self.frames.append(json.loads(frame))
        self.received.set()

    async def messages(self) -> list[dict]:
        # Writers run on the same loop; let them drain the queues.
        for _ in range(5):
            await asyncio.sleep(0)
        frames, self.frames = self.frames, []
        self.received.clear()
        return frames


class ModelSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.servers: list[OutboundServer] = [vless()]
        self.websocket = WebSocketServer()
        self.sync = ModelSync(self.websocket)
        self.sync.register(ModelChannel("outbound_server", lambda: list(self.servers)))

    async def asyncTearDown(self):
        await self.websocket.close()

    async def test_connect_sends_refresh_then_only_changes(self):
        client = Client(self.websocket)
        self.assertEqual(
            await client.messages(),
            [
                {
                    "type": "subscription",
                    "model": "outbound_server",
                    "refresh": True,
                    "payload": [serialize(self.servers[0])],
                    "deleted_ids": [],
                }
            ],
        )

        added = vless(id="added", name="Added")
        self.servers.append(added)
        self.servers[0] = vless(name="Renamed")
        await self.sync.notify("outbound_server")
        [message] = await client.messages()
        self.assertFalse(message["refresh"])
        self.assertEqual([item["id"] for item in message["payload"]], ["vless", "added"])
        self.assertEqual(message["payload"][0]["name"], "Renamed")
        self.assertEqual(message["deleted_ids"], [])

        del self.servers[1]
        await self.sync.notify("outbound_server")
        [message] = await client.messages()
        self.assertEqual((message["payload"], message["deleted_ids"]), ([], ["added"]))

    async def test_no_message_without_visible_changes(self):
        client = Client(self.websocket)
        await client.messages()
        await self.sync.notify("outbound_server")
        # A secret-only change is invisible to clients.
        self.servers[0] = vless(vless_uuid=UUID(int=2))
        await self.sync.notify("outbound_server")
        self.assertEqual(await client.messages(), [])
        with self.assertRaises(KeyError):
            await self.sync.notify("missing")

    async def test_snapshot_includes_writes_without_notify_and_updates_others(self):
        first = Client(self.websocket, "first")
        await first.messages()
        self.servers.append(vless(id="late"))
        second = Client(self.websocket, "second")
        [change] = await first.messages()
        self.assertEqual([item["id"] for item in change["payload"]], ["late"])
        messages = await second.messages()
        self.assertTrue(messages[-1]["refresh"])
        self.assertEqual([item["id"] for item in messages[-1]["payload"]], ["vless", "late"])

    async def test_duplicate_model_and_connection_are_rejected(self):
        with self.assertRaises(ValueError):
            self.sync.register(ModelChannel("outbound_server", list))
        Client(self.websocket)
        with self.assertRaises(ValueError):
            Client(self.websocket)

    async def test_send_error_drops_only_that_connection(self):
        failing = AsyncMock(side_effect=ConnectionError)
        with self.assertLogs("server.main", level="WARNING"):
            self.websocket.connect("failing", failing)
            healthy = Client(self.websocket)
            await healthy.messages()
        self.servers.clear()
        await self.sync.notify("outbound_server")
        [message] = await healthy.messages()
        self.assertEqual(message["deleted_ids"], ["vless"])
        failing.assert_awaited_once()


class ApplicationSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_refresh_notifies_connected_clients(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.enterContext(
            patch("server.main.MihomoClient", return_value=AsyncMock(spec=CoreClient))
        )
        load = self.enterContext(
            patch("server.handlers.subscriptions.load_subscription", new_callable=AsyncMock)
        )
        release = asyncio.Event()

        async def loaded(link):
            await release.wait()
            return [vless()]

        load.side_effect = loaded
        async with asyncio.timeout(2), application() as context:
            context.settings.subscription_link.save(SubscriptionLink(url="https://e.com/s", id="s"))
            client = Client(context.websocket)
            snapshots = await client.messages()
            self.assertEqual(
                [(m["model"], m["refresh"], m["payload"]) for m in snapshots],
                [
                    ("server_settings", True, [serialize(ServerSettings())]),
                    ("subscription_link", True, [{"id": "s", "url_short": "https://e.com"}]),
                    ("reg_filter", True, []),
                    ("outbound_server", True, []),
                    (
                        "task",
                        True,
                        [
                            {"id": "refresh_subscriptions", "status": "stopped"},
                            {"id": "test_outbound_servers", "status": "stopped"},
                        ],
                    ),
                    # The startup refresh starts after the client has connected.
                    ("task", False, [{"id": "refresh_subscriptions", "status": "running"}]),
                ],
            )
            context.settings.server_settings.save(ServerSettings(subscription_refresh_interval=60))
            await context.sync.notify("server_settings")
            [message] = await client.messages()
            self.assertEqual(
                (message["model"], message["refresh"], message["deleted_ids"]),
                ("server_settings", False, []),
            )
            self.assertEqual(message["payload"][0]["subscription_refresh_interval"], 60)
            release.set()
            await client.received.wait()
            await startup_finished(context)
            [servers, settings, task] = await client.messages()
            self.assertEqual(servers["model"], "outbound_server")
            # Only the task whose status changed is sent.
            self.assertEqual(
                (task["model"], task["refresh"], task["payload"]),
                ("task", False, [{"id": "refresh_subscriptions", "status": "stopped"}]),
            )
            self.assertEqual(servers["payload"], [serialize(vless())])
            self.assertEqual(settings["model"], "server_settings")
            self.assertIsNotNone(settings["payload"][0]["last_subscription_refresh"])
