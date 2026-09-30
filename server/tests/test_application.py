import asyncio
import unittest
from contextlib import chdir
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from uuid import UUID

from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from server.cores.core_client import CoreClient
from server.handlers.auto_connect import RETRY_INTERVAL, watch_connected_server
from server.handlers.outbound_test import test_outbound_servers
from server.handlers.subscriptions import refresh_subscriptions
from server.main import PROXY_PORT, TEST_PORT, WebSocketServer, application, configure_handlers
from server.models.application_context import ApplicationContext
from server.models.outbound_server import OutboundProtocol, OutboundServer
from server.models.server_settings import ServerSettings
from server.models.subscription_link import SubscriptionLink
from server.request_error import ErrorCode, RequestError
from server.settings_store import SettingsStore
from server.subscription_loader import SubscriptionError
from server.tests.support import startup_finished


class ApplicationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.core = AsyncMock(spec=CoreClient)
        self.enterContext(patch("server.main.MihomoClient", return_value=self.core))
        # Loading one subscription; init refreshes every saved link.
        self.load = self.enterContext(
            patch(
                "server.handlers.subscriptions.load_subscription",
                new_callable=AsyncMock,
                return_value=[],
            )
        )
        self.link = SubscriptionLink(url="https://example.com/startup")

    async def test_init_refreshes_database_without_delaying_startup(self):
        started, finish = asyncio.Event(), asyncio.Event()
        server = OutboundServer(
            name="New",
            address="new.example.com",
            port=443,
            protocol=OutboundProtocol.VLESS,
            vless_uuid=UUID(int=1),
        )
        old = OutboundServer(
            name="Old",
            address="old.example.com",
            port=443,
            protocol=OutboundProtocol.VLESS,
            vless_uuid=UUID(int=2),
        )

        async def load(link):
            started.set()
            await finish.wait()
            return [server]

        self.load.side_effect = load
        async with asyncio.timeout(2):
            async with application() as context:
                context.settings.subscription_link.save(self.link)
                context.settings.outbound_server.save(old)
                await started.wait()
                # Startup has returned even though the refresh is still waiting.
                self.assertEqual(context.settings.outbound_server.get_all(), [old])
                finish.set()
                await startup_finished(context)
                self.assertEqual(context.settings.outbound_server.get_all(), [server])
                self.load.assert_awaited_once_with(self.link)
        with SettingsStore() as restored:
            self.assertEqual(restored.outbound_server.get_all(), [server])

    async def test_init_failure_preserves_saved_servers(self):
        server = OutboundServer(
            name="Saved",
            address="example.com",
            port=443,
            protocol=OutboundProtocol.VLESS,
            vless_uuid=UUID(int=1),
        )
        self.load.side_effect = RuntimeError("Refresh failed")
        with self.assertLogs("server.handlers.init", level="ERROR"):
            async with application() as context:
                context.settings.subscription_link.save(self.link)
                context.settings.outbound_server.save(server)
                await startup_finished(context)
                self.assertEqual(context.settings.outbound_server.get_all(), [server])
        with SettingsStore() as restored:
            self.assertEqual(restored.outbound_server.get_all(), [server])

    async def test_shutdown_cancels_init_before_closing_settings(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def load(link):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                context.settings.outbound_server.get_all()
                self.core.service_stop.assert_not_awaited()
                cancelled.set()

        self.load.side_effect = load
        async with asyncio.timeout(2):
            async with application() as context:
                context.settings.subscription_link.save(self.link)
                await started.wait()
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(SettingsStore._instance)
        self.core.service_stop.assert_awaited_once()

    async def test_startup_and_cleanup_after_failure(self):
        with self.assertRaisesRegex(RuntimeError, "handler failure"):
            async with application() as context:
                self.assertTrue(Path("settings.sqlite3").is_file())
                self.assertIs(context.settings, SettingsStore())
                self.assertIs(context.core_client, self.core)
                self.core.service_start.assert_awaited_once_with(PROXY_PORT, TEST_PORT)
                self.core.outbound_register.assert_awaited_once_with([])
                raise RuntimeError("handler failure")
        self.core.service_stop.assert_awaited_once()
        self.assertIsNone(SettingsStore._instance)

    async def test_startup_registers_stored_servers_in_the_core(self):
        supported, unsupported = (
            OutboundServer(
                name=name,
                address="example.com",
                port=443,
                protocol=OutboundProtocol.VLESS,
                vless_uuid=UUID(int=1),
            )
            for name in ("supported", "unsupported")
        )
        with SettingsStore() as settings:
            settings.subscription_link.save(self.link)
            settings.outbound_server.add_servers([supported, unsupported])

        def check(server):
            if server.id == unsupported.id:
                raise ValueError("secret provider option")

        self.core.check_outbound_server_config.side_effect = check
        order = []
        self.core.service_start.side_effect = lambda *args: order.append("start")
        self.core.outbound_register.side_effect = lambda servers: order.append("register")
        self.load.side_effect = lambda link: order.append("refresh") or []
        with self.assertLogs("server.handlers.core", level="WARNING") as logs:
            async with application():
                # Stored servers are registered before init refreshes subscriptions.
                self.assertEqual(order, ["start", "register"])
                self.core.outbound_register.assert_awaited_once_with([supported])
                for _ in range(5):
                    await asyncio.sleep(0)  # Let init finish.
                # The refresh registers the servers it stored again.
                self.assertEqual(order, ["start", "register", "refresh", "register"])
        self.assertIn(unsupported.id, logs.output[0])
        self.assertNotIn("secret", logs.output[0])

    async def test_core_start_failure_stops_startup(self):
        self.core.service_start.side_effect = RuntimeError("port is busy")
        with self.assertRaisesRegex(RuntimeError, "port is busy"):
            async with application():
                self.fail("the application must not start")
        self.core.outbound_register.assert_not_awaited()
        self.load.assert_not_awaited()
        self.core.service_stop.assert_awaited_once()
        self.assertIsNone(SettingsStore._instance)

    async def test_handler_can_run_directly_and_on_rescheduled_timer(self):
        calls = []
        invoked = asyncio.Event()
        loop = asyncio.get_running_loop()
        link = SubscriptionLink(url="https://example.com/sub")

        async def handler(context: ApplicationContext):
            self.assertIs(asyncio.get_running_loop(), loop)
            calls.append(context.settings.subscription_link.get_by_id(link.id))
            await context.core_client.test_stop()
            invoked.set()

        async with application() as context:
            context.settings.subscription_link.save(link)
            await handler(context)
            invoked.clear()
            context.scheduler.add_job(
                partial(handler, context), IntervalTrigger(hours=1), id="test"
            )
            changed = context.scheduler.reschedule_job(
                "test", CronTrigger(hour=10, minute=30, timezone=UTC)
            )
            self.assertEqual(changed.next_run_time.hour, 10)
            self.assertEqual(changed.next_run_time.minute, 30)
            context.scheduler.reschedule_job("test", DateTrigger(run_date=datetime.now(UTC)))
            await asyncio.wait_for(invoked.wait(), 2)
            self.assertEqual(calls, [link, link])
            self.assertEqual(self.core.test_stop.await_count, 2)

    async def test_interval_failure_does_not_disable_future_runs(self):
        calls = 0
        completed = asyncio.Event()

        async def handler():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ValueError("example failure")
            completed.set()

        async with application() as context:
            with self.assertLogs("apscheduler.executors.default", level="ERROR"):
                context.scheduler.add_job(handler, IntervalTrigger(seconds=0.02), id="interval")
                await asyncio.wait_for(completed.wait(), 2)
            context.scheduler.remove_job("interval")
            with self.assertRaises(JobLookupError):
                context.scheduler.reschedule_job("interval", IntervalTrigger(hours=1))
            self.assertGreaterEqual(calls, 2)

    async def test_shutdown_waits_for_handler_before_closing_services(self):
        started, finish, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        link = SubscriptionLink(url="https://example.com/sub")
        manager = application()
        context = await manager.__aenter__()

        async def handler():
            started.set()
            await finish.wait()
            context.settings.subscription_link.save(link)
            await context.core_client.test_stop()
            self.core.service_stop.assert_not_awaited()
            finished.set()

        context.scheduler.add_job(handler, DateTrigger(run_date=datetime.now(UTC)), id="active")
        closing = None
        try:
            await asyncio.wait_for(started.wait(), 2)
            closing = asyncio.create_task(manager.__aexit__(None, None, None))
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
            self.core.service_stop.assert_not_awaited()
        finally:
            finish.set()
            if closing is None:
                await manager.__aexit__(None, None, None)
            else:
                await asyncio.wait_for(closing, 2)
        self.assertTrue(finished.is_set())
        self.core.service_stop.assert_awaited_once()
        with SettingsStore() as restored:
            self.assertEqual(restored.subscription_link.get_all(), [link])

    async def test_subscription_refresh_registers_new_servers_in_the_core(self):
        async with application() as context:
            await startup_finished(context)
            self.core.outbound_register.reset_mock()  # Startup registration.
            first = SubscriptionLink(url="https://example.com/one")
            second = SubscriptionLink(url="https://example.com/two")
            context.settings.subscription_link.save(first)
            context.settings.subscription_link.save(second)
            servers = {
                link.id: OutboundServer(
                    name=link.url_short,
                    address="example.com",
                    port=443,
                    subscription_id=link.id,
                    protocol=OutboundProtocol.VLESS,
                    vless_uuid=UUID(int=1),
                )
                for link in (first, second)
            }
            self.load.side_effect = lambda link: [servers[link.id]]
            await refresh_subscriptions(context)
            self.assertEqual([call.args[0] for call in self.load.await_args_list], [first, second])
            self.assertEqual(
                context.settings.outbound_server.get_all(), [servers[first.id], servers[second.id]]
            )
            self.core.outbound_register.assert_awaited_once_with(
                [servers[first.id], servers[second.id]]
            )
            self.core.outbound_connect.assert_not_awaited()

            # A failed refresh keeps the stored servers, so the core is not touched.
            self.core.outbound_register.reset_mock()
            self.load.side_effect = SubscriptionError(first.id)
            with self.assertRaises(SubscriptionError):
                await refresh_subscriptions(context)
            self.core.outbound_register.assert_not_awaited()

    async def test_registration_waits_for_a_running_server_check(self):
        async with application() as context:
            await startup_finished(context)
            self.core.outbound_register.reset_mock()
            async with context.outbound_test_lock:
                refresh = asyncio.create_task(refresh_subscriptions(context))
                for _ in range(5):
                    await asyncio.sleep(0)
                # Servers are stored and sent to clients; the core waits for the check.
                self.assertFalse(refresh.done())
                self.core.outbound_register.assert_not_awaited()
            await refresh
            self.core.outbound_register.assert_awaited_once_with([])

    async def test_server_checks_run_every_hour(self):
        async with application() as context:
            configure_handlers(context)
            job = context.scheduler._scheduler.get_job("test_outbound_servers")
            self.assertIsInstance(job.trigger, IntervalTrigger)
            self.assertEqual(job.trigger.interval, timedelta(hours=1))
            handler = job.args[0]
            self.assertIs(handler.func, test_outbound_servers)
            self.assertEqual(handler.args, (context,))

    async def test_connected_server_is_watched_every_retry_interval(self):
        async with application() as context:
            configure_handlers(context)
            job = context.scheduler._scheduler.get_job("watch_connected_server")
            self.assertEqual(job.trigger.interval, timedelta(seconds=RETRY_INTERVAL))
            handler = job.args[0]
            self.assertIs(handler.func, watch_connected_server)
            self.assertEqual(handler.args, (context,))

    async def test_subscriptions_refresh_every_interval(self):
        with SettingsStore() as settings:
            settings.server_settings.save(ServerSettings(subscription_refresh_interval=600))
            settings.subscription_link.save(self.link)
        async with application() as context:
            await startup_finished(context)
            configure_handlers(context)
            job = context.scheduler.get_job("refresh_subscriptions")
            assert job is not None
            self.assertEqual(job.trigger.interval, timedelta(seconds=600))
            # The first run is one interval after startup: init has just refreshed.
            self.assertGreater(job.next_run_time, datetime.now(UTC) + timedelta(seconds=590))
            self.load.reset_mock()
            refreshed = asyncio.Event()
            self.load.side_effect = lambda link: refreshed.set() or []
            context.scheduler.reschedule_job(
                "refresh_subscriptions", DateTrigger(run_date=datetime.now(UTC))
            )
            await asyncio.wait_for(refreshed.wait(), 2)
            self.load.assert_awaited_once_with(self.link)

    async def test_sync_handlers_are_rejected(self):
        async with application() as context:
            with self.assertRaises(TypeError):
                context.scheduler.add_job(
                    lambda: asyncio.sleep(0), IntervalTrigger(hours=1), id="sync"
                )


class WebSocketScaffoldTests(unittest.IsolatedAsyncioTestCase):
    async def test_routing_and_direct_call_use_the_same_handler(self):
        server = WebSocketServer()
        handler = AsyncMock(return_value={"ok": True})
        server.register("add", "example", handler)
        self.assertEqual(await handler({"n": 1}), {"ok": True})
        self.assertEqual(await server.dispatch("add", "example", {"n": 2}), {"ok": True})
        handler.assert_awaited_with({"n": 2})
        with self.assertRaises(ValueError):
            server.register("add", "example", handler)
        with self.assertRaises(RequestError) as raised:
            await server.dispatch("delete", "example", {})
        self.assertIs(raised.exception.code, ErrorCode.UNKNOWN_REQUEST)
