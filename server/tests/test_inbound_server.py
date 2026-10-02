import asyncio
import socket
import sqlite3
import unittest
from contextlib import chdir
from dataclasses import replace
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import AsyncMock, patch

from server.cores.core_client import CoreClient, InboundError
from server.main import application, configure_handlers
from server.models import (
    DEFAULT_PROXY_PORT,
    InboundFieldError,
    InboundServer,
    InboundType,
    serialize,
)
from server.settings_store import SettingsStore
from server.tests.support import startup_finished
from server.tests.test_requests import Client


def proxy(**values: Any) -> InboundServer:
    values.setdefault("type", InboundType.PROXY)
    values.setdefault("proxy_port", 1080)
    return InboundServer(**values)


class InboundServerModelTests(unittest.TestCase):
    def test_defaults_and_normalization(self):
        inbound = proxy(proxy_listen="::0")
        self.assertEqual(inbound.proxy_listen, "::")
        self.assertTrue(inbound.enabled)
        self.assertIsNone(inbound.error)
        self.assertEqual(proxy().proxy_listen, "127.0.0.1")
        secured = proxy(proxy_username="user", proxy_password="secret")
        self.assertNotIn("secret", repr(secured))
        serialized = serialize(secured)
        assert isinstance(serialized, dict)
        self.assertNotIn("proxy_password", serialized)
        self.assertEqual(serialized["proxy_username"], "user")
        self.assertEqual(serialized["type"], "proxy")

    def test_invalid_values_name_their_field(self):
        cases = {
            "proxy_listen": {"proxy_listen": "localhost"},
            "proxy_port": {"proxy_port": 0},
            "proxy_password": {"proxy_username": "user"},
            "proxy_username": {"proxy_password": "secret"},
            "enabled": {"enabled": 1},
        }
        for name, values in cases.items():
            with self.subTest(name), self.assertRaises(InboundFieldError) as raised:
                proxy(**values)
            self.assertEqual(raised.exception.field, name)
        for username in ("", "a:b"):
            with self.assertRaises(InboundFieldError) as raised:
                proxy(proxy_username=username, proxy_password="secret")
            self.assertEqual(raised.exception.field, "proxy_username")
        with self.assertRaises(InboundFieldError) as raised:
            InboundServer(type=InboundType.PROXY)
        self.assertEqual(raised.exception.field, "proxy_port")
        with self.assertRaises(InboundFieldError) as raised:
            proxy(type="proxy")
        self.assertEqual(raised.exception.field, "type")


class InboundServerStoreTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(chdir(self.enterContext(TemporaryDirectory())))

    def test_default_inbound_is_created_with_the_table_only(self):
        with SettingsStore() as settings:
            (default,) = settings.inbound_server.get_all()
            self.assertEqual(default, replace(default, type=InboundType.PROXY))
            self.assertEqual(
                (default.proxy_listen, default.proxy_port, default.enabled),
                ("127.0.0.1", DEFAULT_PROXY_PORT, True),
            )
            self.assertTrue(settings.inbound_server.delete(default.id))
            self.assertFalse(settings.inbound_server.delete(default.id))
        with SettingsStore() as settings:
            # Deleted by a client, it does not come back.
            self.assertEqual(settings.inbound_server.get_all(), [])

    def test_save_update_and_errors(self):
        with SettingsStore() as settings:
            store = settings.inbound_server
            (default,) = store.get_all()
            secured = proxy(proxy_username="user", proxy_password="secret", enabled=False)
            store.save(secured)
            self.assertEqual(store.get_by_id(secured.id), secured)
            moved = replace(default, proxy_port=1081, proxy_listen="0.0.0.0")
            store.save(moved)
            # Updates keep the insertion order.
            self.assertEqual(store.get_all(), [moved, secured])
            with self.assertRaises(sqlite3.IntegrityError):
                store.save(proxy(proxy_port=1081))
            store.set_error(moved.id, "Port 1081 is already in use")
            store.set_error("missing", "ignored")
            self.assertEqual(
                store.get_by_id(moved.id), replace(moved, error="Port 1081 is already in use")
            )
            self.assertIsNone(store.get_by_id("missing"))


class InboundServerRequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(chdir(self.enterContext(TemporaryDirectory())))
        self.core = AsyncMock(spec=CoreClient)
        self.core.test_port = 20809
        self.enterContext(patch("server.main.MihomoClient", return_value=self.core))
        self.enterContext(
            patch("server.handlers.subscriptions.load_subscription", new=AsyncMock(return_value=[]))
        )
        self.context = await self.enterAsyncContext(application())
        configure_handlers(self.context)
        self.client = Client(self.context.websocket)
        async with asyncio.timeout(2):
            while len(self.client.frames) < 7:
                self.client.received.clear()
                await self.client.received.wait()
        await startup_finished(self.context)
        self.client.frames.clear()
        (self.default,) = self.stored()
        self.core.reset_mock()

    def stored(self) -> list[InboundServer]:
        return self.context.settings.inbound_server.get_all()

    async def test_add_starts_the_listener_before_saving(self):
        payload = {
            "type": "proxy",
            "proxy_port": 1080,
            "proxy_listen": "0.0.0.0",
            "proxy_username": "user",
            "proxy_password": "secret",
        }
        updates, response = await self.client.request("add", "inbound_server", payload)
        self.assertTrue(response["ok"], response)
        inbound_id = response["payload"]["id"]
        added = self.context.settings.inbound_server.get_by_id(inbound_id)
        assert added is not None
        self.assertEqual(added.proxy_password, "secret")
        self.core.inbound_set.assert_awaited_once_with(added)
        self.assertEqual(
            updates,
            [
                {
                    "type": "subscription",
                    "model": "inbound_server",
                    "refresh": False,
                    "payload": [
                        {
                            "id": inbound_id,
                            "type": "proxy",
                            "enabled": True,
                            "proxy_listen": "0.0.0.0",
                            "proxy_port": 1080,
                            "proxy_username": "user",
                            "error": None,
                        }
                    ],
                    "deleted_ids": [],
                }
            ],
        )
        # A disabled inbound is saved without the core.
        self.core.reset_mock()
        _, response = await self.client.request(
            "add", "inbound_server", {"type": "proxy", "proxy_port": 1081, "enabled": False}
        )
        self.assertTrue(response["ok"], response)
        self.core.inbound_set.assert_not_awaited()
        self.assertEqual(len(self.stored()), 3)

    async def test_add_rejects_invalid_payloads(self):
        cases = [
            ({"proxy_port": 1080}, "bad_request", "type"),
            ({"type": "tun", "proxy_port": 1080}, "validation_error", "type"),
            ({"type": "proxy"}, "validation_error", "proxy_port"),
            ({"type": "proxy", "proxy_port": "1080"}, "bad_request", "proxy_port"),
            ({"type": "proxy", "proxy_port": 70000}, "validation_error", "proxy_port"),
            (
                {"type": "proxy", "proxy_port": 1080, "proxy_listen": "lan"},
                "validation_error",
                "proxy_listen",
            ),
            (
                {"type": "proxy", "proxy_port": 1080, "proxy_username": "u"},
                "validation_error",
                "proxy_password",
            ),
            ({"type": "proxy", "proxy_port": 1080, "error": None}, "bad_request", "error"),
            ({"type": "proxy", "proxy_port": 1080, "id": "x"}, "bad_request", "id"),
            ({"type": "proxy", "proxy_port": DEFAULT_PROXY_PORT}, "conflict", "proxy_port"),
            ({"type": "proxy", "proxy_port": 20809}, "conflict", "proxy_port"),
        ]
        for payload, code, field in cases:
            with self.subTest(payload):
                error = await self.client.error("add", "inbound_server", payload)
                self.assertEqual((error["code"], error["details"]), (code, {"field": field}))
        self.core.inbound_set.assert_not_awaited()
        self.assertEqual(self.stored(), [self.default])

    async def test_core_failures_save_nothing(self):
        failures = [
            (InboundError("Port 1080 is already in use", "proxy_port"), "conflict"),
            (
                InboundError("Address 192.0.2.1 is not available", "proxy_listen"),
                "validation_error",
            ),
        ]
        for failure, code in failures:
            self.core.inbound_set.side_effect = failure
            error = await self.client.error(
                "add", "inbound_server", {"type": "proxy", "proxy_port": 1080}
            )
            self.assertEqual(
                (error["code"], error["message"], error["details"]),
                (code, str(failure), {"field": failure.field}),
            )
        self.core.inbound_set.side_effect = RuntimeError("secret diagnostics")
        with self.assertLogs("server.handlers.inbound_server", level="ERROR"):
            error = await self.client.error(
                "change", "inbound_server", {"id": self.default.id, "proxy_port": 1080}
            )
        self.assertEqual(error["code"], "core_error")
        self.assertEqual(error["details"], {"id": self.default.id})
        self.assertNotIn("secret", error["message"])
        self.assertEqual(self.stored(), [self.default])
        self.assertEqual(self.client.frames, [])

    async def test_change_keeps_omitted_fields(self):
        inbound = replace(self.default, error="Port 20808 is already in use")
        self.context.settings.inbound_server.save(inbound)
        await self.context.sync.notify("inbound_server")
        for _ in range(5):
            await asyncio.sleep(0)  # Let the writer send the update.
        self.client.frames.clear()
        updates, response = await self.client.request(
            "change", "inbound_server", {"id": inbound.id, "proxy_port": 1080}
        )
        self.assertTrue(response["ok"], response)
        changed = replace(self.default, proxy_port=1080)
        # A successful start clears the error.
        self.assertEqual(self.stored(), [changed])
        self.core.inbound_set.assert_awaited_once_with(changed)
        self.assertEqual(updates[0]["payload"], [serialize(changed)])
        # The same values retry the start, e.g. after the port was freed.
        _, response = await self.client.request("change", "inbound_server", {"id": inbound.id})
        self.assertTrue(response["ok"], response)
        self.assertEqual(self.core.inbound_set.await_count, 2)

    async def test_change_authentication(self):
        inbound_id = self.default.id
        _, response = await self.client.request(
            "change",
            "inbound_server",
            {"id": inbound_id, "proxy_username": "user", "proxy_password": "old"},
        )
        self.assertTrue(response["ok"], response)
        # The password is never sent, so changing only it sends no update.
        updates, response = await self.client.request(
            "change", "inbound_server", {"id": inbound_id, "proxy_password": "new"}
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(updates, [])
        (stored,) = self.stored()
        self.assertEqual((stored.proxy_username, stored.proxy_password), ("user", "new"))
        self.assertEqual(self.core.inbound_set.await_args.args[0], stored)
        error = await self.client.error(
            "change", "inbound_server", {"id": inbound_id, "proxy_username": None}
        )
        self.assertEqual(error["details"], {"field": "proxy_username"})
        updates, response = await self.client.request(
            "change",
            "inbound_server",
            {"id": inbound_id, "proxy_username": None, "proxy_password": None},
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(self.stored(), [self.default])
        self.assertIsNone(updates[0]["payload"][0]["proxy_username"])

    async def test_change_errors(self):
        cases = [
            ({"proxy_port": 1080}, "bad_request", "id"),
            ({"id": "missing"}, "not_found", "id"),
            ({"id": self.default.id, "type": "proxy"}, "bad_request", "type"),
            ({"id": self.default.id, "enabled": "yes"}, "bad_request", "enabled"),
            ({"id": self.default.id, "proxy_password": 1}, "bad_request", "proxy_password"),
            ({"id": self.default.id, "proxy_port": 20809}, "conflict", "proxy_port"),
        ]
        for payload, code, field in cases:
            with self.subTest(payload):
                error = await self.client.error("change", "inbound_server", payload)
                self.assertEqual((error["code"], error["details"]), (code, {"field": field}))
        other = proxy(proxy_port=1080, enabled=False)
        self.context.settings.inbound_server.save(other)
        # Disabled inbounds keep their ports too.
        error = await self.client.error(
            "change", "inbound_server", {"id": self.default.id, "proxy_port": 1080}
        )
        self.assertEqual((error["code"], error["details"]), ("conflict", {"field": "proxy_port"}))
        self.core.inbound_set.assert_not_awaited()

    async def test_disable_enable_and_delete(self):
        inbound_id = self.default.id
        updates, response = await self.client.request(
            "change", "inbound_server", {"id": inbound_id, "enabled": False}
        )
        self.assertTrue(response["ok"], response)
        self.core.inbound_delete.assert_awaited_once_with(inbound_id)
        self.core.inbound_set.assert_not_awaited()
        self.assertFalse(updates[0]["payload"][0]["enabled"])
        # Changing a disabled inbound does not touch the core.
        await self.client.request("change", "inbound_server", {"id": inbound_id, "proxy_port": 1})
        self.assertEqual(self.core.inbound_delete.await_count, 1)
        self.core.inbound_set.assert_not_awaited()
        _, response = await self.client.request(
            "change", "inbound_server", {"id": inbound_id, "enabled": True}
        )
        self.assertTrue(response["ok"], response)
        self.core.inbound_set.assert_awaited_once()
        self.core.inbound_delete.side_effect = RuntimeError("core is gone")
        with self.assertLogs("server.handlers.inbound_server", level="ERROR"):
            error = await self.client.error("delete", "inbound_server", {"id": inbound_id})
        self.assertEqual(error["code"], "core_error")
        self.assertEqual(len(self.stored()), 1)
        self.core.inbound_delete.side_effect = None
        updates, response = await self.client.request(
            "delete", "inbound_server", {"id": inbound_id}
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(updates[0]["deleted_ids"], [inbound_id])
        self.assertEqual(self.stored(), [])
        error = await self.client.error("delete", "inbound_server", {"id": inbound_id})
        self.assertEqual((error["code"], error["details"]), ("not_found", {"field": "id"}))

    async def test_deleting_a_disabled_inbound_skips_the_core(self):
        disabled = proxy(enabled=False)
        self.context.settings.inbound_server.save(disabled)
        _, response = await self.client.request("delete", "inbound_server", {"id": disabled.id})
        self.assertTrue(response["ok"], response)
        self.core.inbound_delete.assert_not_awaited()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class MihomoInboundTests(unittest.IsolatedAsyncioTestCase):
    """Requests through the application to a real Mihomo."""

    async def asyncSetUp(self):
        self.enterContext(chdir(self.enterContext(TemporaryDirectory())))
        self.enterContext(patch("server.settings_store.DEFAULT_PROXY_PORT", free_port()))
        self.enterContext(
            patch("server.handlers.subscriptions.load_subscription", new=AsyncMock(return_value=[]))
        )
        self.context = await self.enterAsyncContext(application())
        configure_handlers(self.context)
        self.client = Client(self.context.websocket)
        await startup_finished(self.context)
        self.client.frames.clear()

    async def answers(self, port: int) -> bool:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            return False
        try:
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            async with asyncio.timeout(5):
                return await reader.readexactly(2) == b"\x05\x00"
        finally:
            writer.close()

    async def test_inbound_lifecycle(self):
        (default,) = self.context.settings.inbound_server.get_all()
        assert default.proxy_port is not None
        self.assertIsNone(default.error)
        self.assertTrue(await self.answers(default.proxy_port))
        port = free_port()
        _, response = await self.client.request(
            "add", "inbound_server", {"type": "proxy", "proxy_port": port}
        )
        self.assertTrue(response["ok"], response)
        inbound_id = response["payload"]["id"]
        self.assertTrue(await self.answers(port))
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            busy = occupied.getsockname()[1]
            error = await self.client.error(
                "change", "inbound_server", {"id": inbound_id, "proxy_port": busy}
            )
        self.assertEqual(
            (error["code"], error["message"], error["details"]),
            ("conflict", f"Port {busy} is already in use", {"field": "proxy_port"}),
        )
        self.assertTrue(await self.answers(port))
        moved = free_port()
        _, response = await self.client.request(
            "change", "inbound_server", {"id": inbound_id, "proxy_port": moved}
        )
        self.assertTrue(response["ok"], response)
        self.assertTrue(await self.answers(moved))
        self.assertFalse(await self.answers(port))
        _, response = await self.client.request("delete", "inbound_server", {"id": inbound_id})
        self.assertTrue(response["ok"], response)
        self.assertFalse(await self.answers(moved))
        self.assertTrue(await self.answers(default.proxy_port))
