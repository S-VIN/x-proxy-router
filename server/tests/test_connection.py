import asyncio
import unittest
from contextlib import chdir
from dataclasses import replace
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from uuid import UUID

from server.cores.core_client import CoreClient
from server.handlers.core import (
    CoreError,
    ServerFiltered,
    connect_best_outbound_server,
    connect_outbound_server,
    disconnect_filtered_server,
    register_outbound_servers,
)
from server.handlers.subscriptions import refresh_subscriptions
from server.main import application
from server.models import (
    FilterReason,
    OutboundProtocol,
    OutboundServer,
    RegFilter,
    ServerSettings,
    SubscriptionLink,
)
from server.models.application_context import ApplicationContext
from server.settings_store import SettingsStore
from server.tests.support import startup_finished
from server.tests.test_model_sync import Client


def vless(name: str) -> OutboundServer:
    return OutboundServer(
        name=name,
        address="example.com",
        port=443,
        protocol=OutboundProtocol.VLESS,
        vless_uuid=UUID(int=1),
    )


class ConnectionTestCase(unittest.IsolatedAsyncioTestCase):
    """An application with a mocked core and two stored servers, none connected."""

    async def asyncSetUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.core = AsyncMock(spec=CoreClient)
        self.enterContext(patch("server.main.MihomoClient", return_value=self.core))
        self.load = self.enterContext(
            patch(
                "server.handlers.subscriptions.load_subscription",
                new_callable=AsyncMock,
                return_value=[],
            )
        )
        manager = application()
        self.context: ApplicationContext = await manager.__aenter__()
        self.addAsyncCleanup(manager.__aexit__, None, None, None)
        await startup_finished(self.context)
        self.store = self.context.settings.outbound_server
        self.first, self.second = vless("one"), vless("two")
        self.store.add_servers([self.first, self.second])
        self.core.reset_mock()


class ConnectionTests(ConnectionTestCase):
    async def test_connect_switches_the_core_and_remembers_the_server(self):
        client = Client(self.context.websocket)
        await client.messages()
        connected = await connect_outbound_server(self.context, self.first.id)
        assert connected is not None
        self.assertTrue(connected.is_connected)
        await connect_outbound_server(self.context, self.second.id)
        self.assertEqual(
            [call.args[0] for call in self.core.outbound_connect.await_args_list],
            [self.first.id, self.second.id],
        )
        self.assertEqual(self.store.get_connected(), self.store.get_by_id(self.second.id))
        messages = await client.messages()
        self.assertEqual([message["model"] for message in messages], ["outbound_server"] * 2)
        # Clients see both servers change: the old one loses the flag.
        self.assertEqual(
            {server["id"]: server["is_connected"] for server in messages[1]["payload"]},
            {self.first.id: False, self.second.id: True},
        )

    async def test_unknown_server_and_core_failure_keep_the_connection(self):
        await connect_outbound_server(self.context, self.first.id)
        self.assertIsNone(await connect_outbound_server(self.context, "missing"))
        self.core.outbound_connect.side_effect = RuntimeError("secret core detail")
        with (
            self.assertLogs("server.handlers.core", level="ERROR"),
            self.assertRaises(CoreError) as raised,
        ):
            await connect_outbound_server(self.context, self.second.id)
        self.assertNotIn("secret", str(raised.exception))
        connected = self.store.get_connected()
        assert connected is not None
        self.assertEqual(connected.id, self.first.id)

    async def test_filtered_servers_cannot_be_connected(self):
        await connect_outbound_server(self.context, self.first.id)
        self.context.settings.reg_filter.add(RegFilter(reg="^two$"))
        self.store.update_health(
            self.first.id, ping=None, speed=None, rating=0, tests={}, filtered=FilterReason.BY_PING
        )
        for server in (self.second, self.first):
            with self.subTest(server=server.name), self.assertRaises(ServerFiltered):
                await connect_outbound_server(self.context, server.id)
        self.core.outbound_connect.assert_awaited_once_with(self.first.id)
        connected = self.store.get_connected()
        assert connected is not None
        self.assertEqual((connected.id, connected.filtered), (self.first.id, FilterReason.BY_PING))

    async def test_server_filtered_by_name_is_disconnected(self):
        settings = self.context.settings.server_settings
        await connect_outbound_server(self.context, self.first.id)
        # Filters on other servers and filtering by ping keep the connection.
        self.context.settings.reg_filter.add(RegFilter(reg="^two$"))
        self.store.update_health(
            self.first.id, ping=None, speed=None, rating=0, tests={}, filtered=FilterReason.BY_PING
        )
        await disconnect_filtered_server(self.context)
        self.core.outbound_disconnect.assert_not_awaited()
        connected = self.store.get_connected()
        assert connected is not None
        self.assertEqual(connected.id, self.first.id)
        settings.save(replace(settings.get(), auto_connect=True))
        await self.context.sync.notify("server_settings")
        client = Client(self.context.websocket)
        await client.messages()
        # A filter on its name disconnects it and turns auto_connect off.
        self.context.settings.reg_filter.add(RegFilter(reg="^one$"))
        await disconnect_filtered_server(self.context)
        self.core.outbound_disconnect.assert_awaited_once_with()
        self.assertIsNone(self.store.get_connected())
        self.assertFalse(settings.get().auto_connect)
        messages = await client.messages()
        self.assertEqual(
            [message["model"] for message in messages], ["server_settings", "outbound_server"]
        )
        # Nothing is chosen instead.
        await connect_best_outbound_server(self.context)
        self.core.outbound_connect.assert_awaited_once_with(self.first.id)

    async def test_filtered_server_is_marked_disconnected_when_the_core_fails(self):
        await connect_outbound_server(self.context, self.first.id)
        self.context.settings.reg_filter.add(RegFilter(reg="^one$"))
        self.core.outbound_disconnect.side_effect = RuntimeError("down")
        with self.assertLogs("server.handlers.core", level="ERROR"):
            await disconnect_filtered_server(self.context)
        self.assertIsNone(self.store.get_connected())

    async def test_registration_keeps_a_server_filtered_by_ping_but_not_by_name(self):
        settings = self.context.settings.server_settings
        await connect_outbound_server(self.context, self.first.id)
        self.store.update_health(
            self.first.id, ping=None, speed=None, rating=0, tests={}, filtered=FilterReason.BY_PING
        )
        self.core.reset_mock()
        # Filtered servers stay registered; one filtered by ping stays connected.
        await register_outbound_servers(self.context)
        [registered] = self.core.outbound_register.await_args.args
        self.assertEqual({server.id for server in registered}, {self.first.id, self.second.id})
        self.core.outbound_connect.assert_awaited_once_with(self.first.id)
        connected = self.store.get_connected()
        assert connected is not None
        self.assertEqual(connected.id, self.first.id)
        # One filtered by name, e.g. by an older version, is not connected again.
        settings.save(replace(settings.get(), auto_connect=True))
        self.context.settings.reg_filter.add(RegFilter(reg="one"))
        self.core.reset_mock()
        with self.assertLogs("server.handlers.core", level="INFO"):
            await register_outbound_servers(self.context)
        self.core.outbound_connect.assert_not_awaited()
        self.assertIsNone(self.store.get_connected())
        self.assertFalse(settings.get().auto_connect)

    async def test_registration_connects_the_remembered_server_again(self):
        self.store.set_connected(self.second.id)
        order = []
        self.core.outbound_register.side_effect = lambda servers: order.append("register")
        self.core.outbound_connect.side_effect = lambda server_id: order.append(server_id)
        await register_outbound_servers(self.context)
        self.assertEqual(order, ["register", self.second.id])
        connected = self.store.get_connected()
        assert connected is not None
        self.assertEqual(connected.id, self.second.id)

    async def test_refresh_keeps_the_connection(self):
        link = SubscriptionLink(url="https://example.com/sub")
        self.context.settings.subscription_link.save(link)
        self.store.set_connected(self.first.id)
        self.load.return_value = [vless("one"), vless("three")]
        await refresh_subscriptions(self.context)
        self.core.outbound_connect.assert_awaited_once_with(self.first.id)
        connected = self.store.get_connected()
        assert connected is not None
        self.assertEqual(connected.id, self.first.id)

    async def test_connection_is_dropped_when_the_server_cannot_be_used(self):
        self.store.set_connected(self.first.id)

        def check(server):
            if server.id == self.first.id:
                raise ValueError("unsupported")

        self.core.check_outbound_server_config.side_effect = check
        client = Client(self.context.websocket)
        await client.messages()
        with self.assertLogs("server.handlers.core", level="WARNING"):
            await register_outbound_servers(self.context)
        self.core.outbound_connect.assert_not_awaited()
        self.assertIsNone(self.store.get_connected())
        [message] = await client.messages()
        self.assertEqual(message["model"], "outbound_server")

        # The core refuses the remembered server: the flag is cleared as well.
        self.core.check_outbound_server_config.side_effect = None
        self.store.set_connected(self.second.id)
        self.core.outbound_connect.side_effect = RuntimeError("failed")
        with self.assertLogs("server.handlers.core", level="ERROR"):
            await register_outbound_servers(self.context)
        self.assertIsNone(self.store.get_connected())


class AutoConnectTests(ConnectionTestCase):
    def rate(self, server: OutboundServer, rating: int | None) -> None:
        self.store.update_health(
            server.id, ping=None, speed=None, rating=rating, tests={}, filtered=None
        )

    def set_auto_connect(self, enabled: bool) -> None:
        settings = self.context.settings.server_settings
        settings.save(replace(settings.get(), auto_connect=enabled))

    def connected_id(self) -> str | None:
        connected = self.store.get_connected()
        return connected.id if connected is not None else None

    async def test_best_rated_server_that_may_be_connected(self):
        named, no_ping, unchecked = vless("three"), vless("four"), vless("five")
        self.store.add_servers([named, no_ping, unchecked])
        self.rate(self.first, 50)
        self.rate(self.second, 90)
        self.rate(named, 100)
        self.context.settings.reg_filter.add(RegFilter(reg="^three$"))
        self.store.update_health(
            no_ping.id, ping=None, speed=None, rating=95, tests={}, filtered=FilterReason.BY_PING
        )
        # The mode is off by default.
        await connect_best_outbound_server(self.context)
        self.core.outbound_connect.assert_not_awaited()
        self.set_auto_connect(True)
        client = Client(self.context.websocket)
        await client.messages()
        await connect_best_outbound_server(self.context)
        self.core.outbound_connect.assert_awaited_once_with(self.second.id)
        self.assertEqual(self.connected_id(), self.second.id)
        [message] = await client.messages()
        self.assertEqual(message["model"], "outbound_server")

    async def test_unchecked_and_zero_rated_servers_are_not_chosen(self):
        self.set_auto_connect(True)
        self.rate(self.first, 0)
        await connect_best_outbound_server(self.context)
        self.core.outbound_connect.assert_not_awaited()
        self.assertIsNone(self.connected_id())

    async def test_only_a_higher_rating_replaces_the_connected_server(self):
        self.rate(self.first, 80)
        self.rate(self.second, 80)
        self.set_auto_connect(True)
        # Equal ratings keep the stored order.
        await connect_best_outbound_server(self.context)
        self.assertEqual(self.connected_id(), self.first.id)
        self.store.set_connected(self.second.id)
        await connect_best_outbound_server(self.context)
        self.assertEqual(self.connected_id(), self.second.id)
        self.rate(self.first, 81)
        await connect_best_outbound_server(self.context)
        self.assertEqual(self.connected_id(), self.first.id)
        self.assertEqual(
            [call.args[0] for call in self.core.outbound_connect.await_args_list],
            [self.first.id, self.first.id],
        )

    async def test_server_filtered_by_ping_or_unchecked_is_replaced(self):
        self.rate(self.first, 40)
        self.rate(self.second, 90)
        await connect_outbound_server(self.context, self.second.id)
        self.set_auto_connect(True)
        self.store.update_health(
            self.second.id, ping=None, speed=None, rating=0, tests={}, filtered=FilterReason.BY_PING
        )
        await connect_best_outbound_server(self.context)
        self.assertEqual(self.connected_id(), self.first.id)
        # A server that is not checked yet gives way to any rated one.
        third = vless("three")
        self.store.add_servers([third])
        self.store.set_connected(third.id)
        await connect_best_outbound_server(self.context)
        self.assertEqual(self.connected_id(), self.first.id)

    async def test_next_best_server_is_tried_when_the_core_fails(self):
        third = vless("three")
        self.store.add_servers([third])
        self.rate(self.first, 50)
        self.rate(self.second, 90)
        self.rate(third, 70)
        self.set_auto_connect(True)

        def connect(server_id):
            if server_id == self.second.id:
                raise RuntimeError("not registered")

        self.core.outbound_connect.side_effect = connect
        with self.assertLogs("server.handlers.core", level="ERROR"):
            await connect_best_outbound_server(self.context)
        self.assertEqual(self.connected_id(), third.id)
        # Only better servers are tried; when none works, the connection stays.
        self.core.reset_mock()
        self.core.outbound_connect.side_effect = RuntimeError("down")
        with self.assertLogs("server.handlers.core", level="ERROR"):
            await connect_best_outbound_server(self.context)
        self.core.outbound_connect.assert_awaited_once_with(self.second.id)
        self.assertEqual(self.connected_id(), third.id)

    async def test_client_choice_turns_auto_connect_off(self):
        settings = self.context.settings.server_settings
        self.rate(self.first, 40)
        self.rate(self.second, 90)
        self.set_auto_connect(True)
        client = Client(self.context.websocket)
        await client.messages()
        # Failed choices change nothing.
        self.assertIsNone(await connect_outbound_server(self.context, "missing"))
        self.core.outbound_connect.side_effect = RuntimeError("failed")
        with self.assertLogs("server.handlers.core", level="ERROR"), self.assertRaises(CoreError):
            await connect_outbound_server(self.context, self.first.id)
        self.assertTrue(settings.get().auto_connect)
        self.assertEqual(await client.messages(), [])
        self.core.outbound_connect.side_effect = None
        await connect_outbound_server(self.context, self.first.id)
        self.assertFalse(settings.get().auto_connect)
        messages = await client.messages()
        self.assertEqual(
            [message["model"] for message in messages],
            [
                "server_settings",
                "outbound_server",
            ],
        )
        self.assertIs(messages[0]["payload"][0]["auto_connect"], False)
        # The lower rated server the client chose stays.
        await connect_best_outbound_server(self.context)
        self.assertEqual(self.connected_id(), self.first.id)
        # Settings did not change this time, so only the servers are sent.
        await connect_outbound_server(self.context, self.second.id)
        messages = await client.messages()
        self.assertEqual([message["model"] for message in messages], ["outbound_server"])

    async def test_waiting_auto_connect_does_not_replace_the_client_choice(self):
        self.rate(self.first, 40)
        self.rate(self.second, 90)
        self.set_auto_connect(True)
        async with self.context.core_lock:
            chosen = asyncio.create_task(connect_outbound_server(self.context, self.first.id))
            best = asyncio.create_task(connect_best_outbound_server(self.context))
            await asyncio.sleep(0)
        await asyncio.gather(chosen, best)
        self.core.outbound_connect.assert_awaited_once_with(self.first.id)
        self.assertEqual(self.connected_id(), self.first.id)
        self.assertFalse(self.context.settings.server_settings.get().auto_connect)

    async def test_refresh_connects_the_best_server_when_the_connected_one_is_gone(self):
        self.context.settings.subscription_link.save(
            SubscriptionLink(url="https://example.com/sub")
        )
        self.rate(self.second, 70)
        self.store.set_connected(self.first.id)
        self.set_auto_connect(True)
        self.load.return_value = [vless("two"), vless("three")]
        await refresh_subscriptions(self.context)
        self.core.outbound_connect.assert_awaited_once_with(self.second.id)
        self.assertEqual(self.connected_id(), self.second.id)


class StartupConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_connects_the_remembered_server(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        core = AsyncMock(spec=CoreClient)
        self.enterContext(patch("server.main.MihomoClient", return_value=core))
        self.enterContext(
            patch("server.handlers.subscriptions.load_subscription", new_callable=AsyncMock)
        )
        server = vless("one")
        with SettingsStore() as settings:
            settings.outbound_server.save(server)
            settings.outbound_server.set_connected(server.id)
        async with application() as context:
            core.outbound_register.assert_awaited_once_with([replace(server, is_connected=True)])
            core.outbound_connect.assert_awaited_once_with(server.id)
            await startup_finished(context)

    async def test_startup_connects_the_best_server_in_auto_mode(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        core = AsyncMock(spec=CoreClient)
        self.enterContext(patch("server.main.MihomoClient", return_value=core))
        self.enterContext(
            patch("server.handlers.subscriptions.load_subscription", new_callable=AsyncMock)
        )
        remembered, best = vless("one"), vless("two")
        with SettingsStore() as settings:
            settings.server_settings.save(ServerSettings(auto_connect=True))
            settings.outbound_server.add_servers([remembered, best])
            for server, rating in ((remembered, 30), (best, 90)):
                settings.outbound_server.update_health(
                    server.id, ping=None, speed=None, rating=rating, tests={}, filtered=None
                )
            settings.outbound_server.set_connected(remembered.id)
        async with application() as context:
            # The remembered server is connected again first, then the best one.
            self.assertEqual(
                [call.args[0] for call in core.outbound_connect.await_args_list],
                [remembered.id, best.id],
            )
            connected = context.settings.outbound_server.get_connected()
            assert connected is not None
            self.assertEqual(connected.id, best.id)
            await startup_finished(context)
