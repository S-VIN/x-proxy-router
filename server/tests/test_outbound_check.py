import asyncio
import json
import socket
import unittest
from contextlib import chdir
from dataclasses import replace
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from uuid import UUID

from aiohttp import ClientSession
from aiohttp_socks import ProxyConnector

from server.cores.core_client import CoreClient
from server.cores.mihomo.mihomo_client import MihomoClient
from server.handlers import outbound_test as handler
from server.handlers.core import connect_outbound_server, register_outbound_servers
from server.handlers.subscriptions import refresh_subscriptions
from server.main import application
from server.models import (
    FilterReason,
    OutboundProtocol,
    OutboundServer,
    OutboundTest,
    OutboundTestRule,
    RegFilter,
    ServerSettings,
    SubscriptionLink,
)
from server.models.application_context import ApplicationContext
from server.tasks import TaskCancelled
from server.tests.support import startup_finished
from server.tests.test_model_sync import Client


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def vless(port: int, **changes) -> OutboundServer:
    return OutboundServer(
        name=f"server-{port}",
        address="127.0.0.1",
        port=port,
        protocol=OutboundProtocol.VLESS,
        vless_uuid=UUID(int=1),
        **changes,
    )


def hysteria() -> OutboundServer:
    return OutboundServer(
        name="hysteria",
        address="127.0.0.1",
        port=1,
        protocol=OutboundProtocol.HYSTERIA,
        hysteria_auth="auth",
    )


def outbound_test(alias: str, url: str, rule: OutboundTestRule) -> OutboundTest:
    return OutboundTest(url=url, alias=alias, rule=rule)


class RatingTests(unittest.TestCase):
    def test_parts_and_weights(self):
        full = handler.FULL_SPEED
        self.assertEqual(handler.server_rating(0, round(full), {"a": True}), 100)
        self.assertEqual(handler.server_rating(500, 0, {"a": False}), 0)
        # Speed above 1 Mbit/s earns no extra points; ping 250 ms earns half.
        self.assertEqual(handler.server_rating(250, round(full * 10), {"a": True}), 85)
        self.assertEqual(handler.server_rating(0, round(full), {"a": True, "b": False}), 80)

    def test_unmeasured_parts_cost_no_points(self):
        full = round(handler.FULL_SPEED)
        # No ping (not TCP) and no configured tests: the other parts fill the weight.
        self.assertEqual(handler.server_rating(None, full, {"a": True}), 100)
        self.assertEqual(handler.server_rating(0, full, {}), 100)
        self.assertEqual(handler.server_rating(None, full, {}), 100)
        self.assertEqual(handler.server_rating(None, round(full / 2), {}), 50)
        self.assertEqual(handler.server_rating(None, 0, {"a": True, "b": True}), 57)

    def test_tcp_detection(self):
        self.assertTrue(handler.uses_tcp(vless(1)))
        self.assertFalse(handler.uses_tcp(hysteria()))


class PingTests(unittest.IsolatedAsyncioTestCase):
    async def test_best_of_attempts_and_unreachable(self):
        listener = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        self.addAsyncCleanup(listener.wait_closed)
        self.addCleanup(listener.close)
        port = listener.sockets[0].getsockname()[1]
        ping = await handler.tcp_ping("127.0.0.1", port)
        assert ping is not None
        self.assertLessEqual(ping, 500)
        self.assertIsNone(await handler.tcp_ping("127.0.0.1", free_port()))
        self.assertIsNone(await handler.tcp_ping("name.invalid", port))

    async def test_slow_connections_are_abandoned(self):
        attempts = 0

        async def slow(*args):
            nonlocal attempts
            attempts += 1
            await asyncio.sleep(1)

        with (
            patch("server.outbound_probe.PING_LIMIT", 0.05),
            patch("server.outbound_probe.asyncio.open_connection", slow),
        ):
            self.assertIsNone(await handler.tcp_ping("127.0.0.1", 1))
        self.assertEqual(attempts, 3)


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    """The core and network checks are mocked; see MihomoCheckTests for real traffic."""

    async def asyncSetUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.core = AsyncMock(spec=CoreClient)
        self.core.test_port = 1080
        self.enterContext(patch("server.main.MihomoClient", return_value=self.core))
        self.enterContext(
            patch(
                "server.handlers.subscriptions.load_subscription",
                new_callable=AsyncMock,
                return_value=[],
            )
        )
        self.ping = self.enterContext(
            patch.object(handler, "tcp_ping", new_callable=AsyncMock, return_value=100)
        )
        self.speed = self.enterContext(
            patch.object(
                handler,
                "download_speed",
                new_callable=AsyncMock,
                return_value=round(handler.FULL_SPEED),
            )
        )
        self.run_test = self.enterContext(
            patch.object(handler, "run_test", new_callable=AsyncMock, return_value=True)
        )
        manager = application()
        self.context: ApplicationContext = await manager.__aenter__()
        self.addAsyncCleanup(manager.__aexit__, None, None, None)
        await startup_finished(self.context)
        self.tests = (
            outbound_test(
                "google", "https://www.gstatic.com/generate_204", OutboundTestRule.STATUS_204
            ),
            outbound_test("site", "https://example.com/", OutboundTestRule.STATUS_BELOW_503),
        )
        self.context.settings.server_settings.save(ServerSettings(outbound_tests=self.tests))

    def saved(self, server: OutboundServer) -> OutboundServer:
        self.context.settings.outbound_server.save(server)
        return server

    async def test_tcp_server_passes_all_steps(self):
        server = self.saved(vless(443, ping=1, rating=1))
        self.run_test.side_effect = [True, False]
        client = Client(self.context.websocket)
        await client.messages()
        updated = await handler.test_outbound(self.context, server)
        assert updated is not None
        self.ping.assert_awaited_once_with("127.0.0.1", 443)
        self.core.test_connect.assert_awaited_once_with(server.id)
        self.core.test_stop.assert_awaited_once()
        self.assertEqual([call.args[1] for call in self.run_test.await_args_list], list(self.tests))
        self.assertEqual(updated.tests, {"google": True, "site": False})
        self.assertEqual((updated.ping, updated.speed), (100, round(handler.FULL_SPEED)))
        assert updated.speed is not None and updated.tests is not None
        self.assertEqual(updated.rating, handler.server_rating(100, updated.speed, updated.tests))
        self.assertEqual(self.context.settings.outbound_server.get_by_id(server.id), updated)
        messages = await client.messages()
        self.assertEqual([message["model"] for message in messages], ["outbound_server"])
        self.assertEqual(messages[0]["payload"][0]["tests"], {"google": True, "site": False})

    async def test_unreachable_server_stops_after_ping(self):
        server = self.saved(vless(443, speed=500, tests={"old": True}))
        self.ping.return_value = None
        updated = await handler.test_outbound(self.context, server)
        assert updated is not None
        self.core.test_connect.assert_not_awaited()
        self.speed.assert_not_awaited()
        self.run_test.assert_not_awaited()
        self.assertEqual(
            (updated.ping, updated.speed, updated.rating, updated.tests, updated.filtered),
            (None, None, 0, {"google": False, "site": False}, FilterReason.BY_PING),
        )
        # The next check that gets through the ping clears the reason.
        self.ping.return_value = 100
        updated = await handler.test_outbound(self.context, updated)
        assert updated is not None
        self.assertIsNone(updated.filtered)

    async def test_non_tcp_server_is_not_pinged_and_loses_no_points(self):
        server = self.saved(hysteria())
        updated = await handler.test_outbound(self.context, server)
        assert updated is not None
        self.ping.assert_not_awaited()
        self.core.test_connect.assert_awaited_once_with(server.id)
        self.assertIsNone(updated.ping)
        self.assertEqual(updated.rating, 100)
        self.assertIsNone(updated.filtered)

    async def test_endpoint_is_released_when_a_check_fails(self):
        server = self.saved(vless(443))
        self.speed.side_effect = RuntimeError("probe failure")
        self.core.test_stop.side_effect = RuntimeError("core stopped")
        with (
            self.assertLogs("server.handlers.outbound_test", level="ERROR"),
            self.assertRaisesRegex(RuntimeError, "probe failure"),
        ):
            await handler.test_outbound(self.context, server)
        self.core.test_stop.assert_awaited_once()
        stored = self.context.settings.outbound_server.get_by_id(server.id)
        assert stored is not None
        self.assertIsNone(stored.rating)
        self.assertFalse(self.context.outbound_test_lock.locked())

    async def test_checks_share_the_endpoint_one_at_a_time(self):
        first, second = self.saved(vless(1)), self.saved(vless(2))
        active = []
        overlaps = []

        async def speed(session):
            active.append(session)
            overlaps.append(len(active))
            await asyncio.sleep(0.01)
            active.remove(session)
            return 0

        self.speed.side_effect = speed
        await asyncio.gather(
            handler.test_outbound(self.context, first),
            handler.test_outbound(self.context, second),
        )
        self.assertEqual(overlaps, [1, 1])
        self.assertEqual(
            [call.args[0] for call in self.core.test_connect.await_args_list],
            [first.id, second.id],
        )

    async def test_server_deleted_during_check_is_not_restored(self):
        server = self.saved(vless(443))

        async def delete(session):
            self.context.settings.outbound_server.delete(server.id)
            return 0

        self.speed.side_effect = delete
        client = Client(self.context.websocket)
        await client.messages()
        self.assertIsNone(await handler.test_outbound(self.context, server))
        self.assertEqual(self.context.settings.outbound_server.get_all(), [])
        self.assertEqual(await client.messages(), [])

    async def test_subscription_changes_during_check_are_kept(self):
        server = self.saved(vless(443))
        changed = vless(443, id=server.id, path="/new")

        async def refresh(session):
            self.context.settings.outbound_server.update_servers([changed])
            return 0

        self.speed.side_effect = refresh
        updated = await handler.test_outbound(self.context, server)
        assert updated is not None
        self.assertEqual(updated.path, "/new")
        self.assertEqual(self.context.settings.outbound_server.get_by_id(server.id), updated)

    def full_rating(self) -> int:
        return handler.server_rating(
            100, round(handler.FULL_SPEED), {test.alias: True for test in self.tests}
        )

    async def test_servers_are_checked_one_after_another(self):
        first, broken, deleted, last = (self.saved(vless(port)) for port in (1, 2, 3, 4))
        checked = []

        async def connect(server_id):
            checked.append(server_id)
            if server_id == first.id:
                self.context.settings.outbound_server.delete(deleted.id)
            if server_id == broken.id:
                raise RuntimeError("not registered in the core")

        self.core.test_connect.side_effect = connect
        with self.assertLogs("server.handlers.outbound_test", level="ERROR") as logs:
            await handler.test_outbound_servers(self.context)
        # The deleted server is skipped; the failed one does not stop the run.
        self.assertEqual(checked, [first.id, broken.id, last.id])
        self.assertEqual(len(logs.output), 1)
        self.assertIn(broken.id, logs.output[0])
        ratings = {
            server.id: server.rating for server in self.context.settings.outbound_server.get_all()
        }
        rating = self.full_rating()
        self.assertEqual(ratings, {first.id: rating, broken.id: None, last.id: rating})

    async def test_run_skips_servers_filtered_by_name_but_not_by_ping(self):
        named, no_ping, plain, later = (
            self.saved(replace(vless(port), name=name))
            for port, name in ((1, "RU 1"), (2, "NL 1"), (3, "NL 2"), (4, "RU 2"))
        )
        self.context.settings.outbound_server.update_health(
            no_ping.id, ping=None, speed=None, rating=0, tests={}, filtered=FilterReason.BY_PING
        )
        self.context.settings.reg_filter.add(RegFilter(reg="^RU 1$"))
        checked = []

        async def connect(server_id):
            checked.append(server_id)
            if server_id == no_ping.id:
                # A filter added during the run applies to the servers not checked yet.
                self.context.settings.reg_filter.add(RegFilter(reg="^RU"))

        self.core.test_connect.side_effect = connect
        await handler.test_outbound_servers(self.context)
        self.assertEqual(checked, [no_ping.id, plain.id])
        stored = {server.id: server for server in self.context.settings.outbound_server.get_all()}
        self.assertIsNone(stored[no_ping.id].filtered)
        rating = self.full_rating()
        self.assertEqual(
            [stored[server.id].rating for server in (named, no_ping, plain, later)],
            [None, rating, rating, None],
        )

    async def test_changed_server_is_checked_with_stored_parameters(self):
        server = self.saved(vless(1))
        self.context.settings.outbound_server.save(replace(server, port=2))
        await handler.test_outbound_servers(self.context)
        self.ping.assert_awaited_once_with("127.0.0.1", 2)

    async def test_refresh_stops_the_run(self):
        first, second = self.saved(vless(1)), self.saved(vless(2))
        checking, finish = asyncio.Event(), asyncio.Event()

        async def speed(session):
            checking.set()
            await finish.wait()
            return 0

        self.speed.side_effect = speed
        run = asyncio.create_task(handler.test_outbound_servers(self.context))
        await checking.wait()
        await refresh_subscriptions(self.context)
        with self.assertRaises(TaskCancelled):
            await run
        # The check was cut off: the endpoint is released and nothing is stored.
        self.core.test_connect.assert_awaited_once_with(first.id)
        self.core.test_stop.assert_awaited_once()
        self.assertFalse(self.context.outbound_test_lock.locked())
        self.assertFalse(self.context.tasks.running("test_outbound_servers"))
        # load_subscription returns no servers, so the refresh removed both.
        self.assertEqual(self.context.settings.outbound_server.get_all(), [])
        self.assertNotIn(
            second.id, [call.args[0] for call in self.core.test_connect.await_args_list]
        )

    async def test_run_is_skipped_while_subscriptions_refresh(self):
        self.saved(vless(1))
        loading, finish = asyncio.Event(), asyncio.Event()

        async def load(link):
            loading.set()
            await finish.wait()
            return []

        self.context.settings.subscription_link.save(SubscriptionLink(url="https://example.com/s"))
        self.enterContext(patch("server.handlers.subscriptions.load_subscription", load))
        refresh = asyncio.create_task(refresh_subscriptions(self.context))
        await loading.wait()
        self.assertIsNone(await handler.test_outbound_servers(self.context))
        self.core.test_connect.assert_not_awaited()
        finish.set()
        await refresh

    async def test_second_run_waits_for_the_running_one(self):
        server = self.saved(vless(1))
        checking, finish = asyncio.Event(), asyncio.Event()

        async def speed(session):
            checking.set()
            await finish.wait()
            return 0

        self.speed.side_effect = speed
        first = asyncio.create_task(handler.test_outbound_servers(self.context))
        await checking.wait()
        second = asyncio.create_task(handler.test_outbound_servers(self.context))
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertFalse(second.done())
        finish.set()
        await asyncio.gather(first, second)
        # One run only: the server was checked once.
        self.core.test_connect.assert_awaited_once_with(server.id)

    async def test_shutdown_stops_the_run(self):
        self.saved(vless(1))
        checking = asyncio.Event()

        async def speed(session):
            checking.set()
            await asyncio.Event().wait()

        self.speed.side_effect = speed
        run = asyncio.create_task(handler.test_outbound_servers(self.context))
        await checking.wait()
        await self.context.tasks.cancel_all()
        with self.assertRaises(TaskCancelled):
            await run
        self.core.test_stop.assert_awaited_once()

    async def test_no_servers(self):
        await handler.test_outbound_servers(self.context)
        self.core.test_connect.assert_not_awaited()


class MihomoCheckTests(unittest.IsolatedAsyncioTestCase):
    """Real traffic: Mihomo -> local VLESS relay -> local HTTP server."""

    async def asyncSetUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.core = MihomoClient()
        self.enterContext(patch("server.main.MihomoClient", return_value=self.core))
        self.enterContext(patch("server.main.PROXY_PORT", free_port()))
        self.enterContext(patch("server.main.TEST_PORT", free_port()))
        self.enterContext(
            patch(
                "server.handlers.subscriptions.load_subscription",
                new_callable=AsyncMock,
                return_value=[],
            )
        )
        self.requests: list[tuple[str, str]] = []
        self.targets: list[str] = []
        self.writers: list[asyncio.StreamWriter] = []
        self.http_port = await self.listen(self.http)
        self.relay_port = await self.listen(self.vless_relay)
        manager = application()
        self.context: ApplicationContext = await manager.__aenter__()
        self.addAsyncCleanup(manager.__aexit__, None, None, None)
        # application() has started the core; no servers were stored yet.
        self.assertIsNotNone(self.core.test_port)

    async def asyncTearDown(self):
        for writer in self.writers:
            writer.close()

    async def listen(self, handle) -> int:
        async def tracked(reader, writer):
            self.writers.append(writer)
            try:
                await handle(reader, writer)
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()

        listener = await asyncio.start_server(tracked, "127.0.0.1", 0)
        self.addAsyncCleanup(listener.wait_closed)
        self.addCleanup(listener.close)
        return listener.sockets[0].getsockname()[1]

    async def http(self, reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        path = request.split(b" ")[1].decode()
        headers = request.decode().lower()
        self.requests.append((path, "accept-encoding: identity" if "identity" in headers else ""))
        if path == "/hang":
            await asyncio.sleep(3600)
        status, extra, body = 200, "", b""
        if path.startswith("/down"):
            body = b"x" * handler.SPEED_TEST_BYTES
        elif path.startswith("/status/"):
            status = int(path.removeprefix("/status/"))
        elif path == "/redirect":
            status, extra = 302, "Location: /status/503\r\n"
        writer.write(
            f"HTTP/1.1 {status} X\r\nContent-Length: {len(body)}\r\n{extra}"
            "Connection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()

    async def vless_relay(self, reader, writer):
        """A VLESS server with the test UUID that connects to the requested target."""
        header = await reader.readexactly(18)
        self.assertEqual(header[1:17], UUID(int=1).bytes)
        await reader.readexactly(header[17])
        command = await reader.readexactly(4)  # command, port, address type
        port = int.from_bytes(command[1:3])
        if command[3] == 2:
            host = (await reader.readexactly((await reader.readexactly(1))[0])).decode()
        else:
            host = socket.inet_ntop(
                socket.AF_INET if command[3] == 1 else socket.AF_INET6,
                await reader.readexactly(4 if command[3] == 1 else 16),
            )
        self.targets.append(f"{host}:{port}")
        target_reader, target_writer = await asyncio.open_connection(host, port)
        self.writers.append(target_writer)
        writer.write(b"\x00\x00")

        async def pipe(source, destination):
            try:
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()
            except ConnectionError:
                pass
            finally:
                destination.close()

        await asyncio.gather(pipe(reader, target_writer), pipe(target_reader, writer))

    async def test_all_steps_through_the_test_endpoint(self):
        base = f"http://127.0.0.1:{self.http_port}"
        closed = free_port()
        tests = (
            outbound_test("204", f"{base}/status/204", OutboundTestRule.STATUS_204),
            outbound_test("503", f"{base}/status/503", OutboundTestRule.STATUS_BELOW_503),
            outbound_test("redirect", f"{base}/redirect", OutboundTestRule.STATUS_BELOW_400),
            outbound_test("hang", f"{base}/hang", OutboundTestRule.ANY_STATUS),
            outbound_test("closed", f"http://127.0.0.1:{closed}/", OutboundTestRule.ANY_STATUS),
        )
        self.context.settings.server_settings.save(ServerSettings(outbound_tests=tests))
        server = vless(self.relay_port)
        dead = vless(free_port())
        self.context.settings.outbound_server.add_servers([server, dead])
        await self.core.outbound_register([server, dead])
        await self.core.outbound_connect(dead.id)
        with (
            patch("server.outbound_probe.SPEED_TEST_URL", f"{base}/down"),
            patch("server.outbound_probe.REQUEST_TIMEOUT", 1),
        ):
            updated = await handler.test_outbound(self.context, server)
        assert updated is not None
        self.assertEqual(
            updated.tests,
            {"204": True, "503": False, "redirect": True, "hang": False, "closed": False},
        )
        assert updated.ping is not None and updated.speed is not None
        assert updated.tests is not None
        self.assertLessEqual(updated.ping, 500)
        self.assertGreater(updated.speed, handler.FULL_SPEED)
        self.assertEqual(
            updated.rating, handler.server_rating(updated.ping, updated.speed, updated.tests)
        )
        # Redirects are not followed; host names go to the proxy; no compression.
        self.assertEqual(
            self.requests,
            [
                ("/down", "accept-encoding: identity"),
                ("/status/204", ""),
                ("/status/503", ""),
                ("/redirect", ""),
                ("/hang", ""),
            ],
        )
        # Every request, including the one to a closed port, went through the relay.
        self.assertEqual(set(self.targets), {f"127.0.0.1:{self.http_port}", f"127.0.0.1:{closed}"})
        proxies = (await self.core.rest_client.get_proxies())["proxies"]
        self.assertEqual(proxies["test"]["now"], "REJECT")
        self.assertEqual(proxies["main"]["now"], dead.id)
        stored = self.context.settings.outbound_server.get_by_id(server.id)
        self.assertEqual(stored, updated)
        self.assertEqual(json.loads(json.dumps(updated.tests)), updated.tests)

    async def test_connected_server_survives_registration(self):
        server, other = vless(self.relay_port), vless(free_port())
        self.context.settings.outbound_server.add_servers([server, other])
        await register_outbound_servers(self.context)
        await connect_outbound_server(self.context, server.id)
        await self.core.test_connect(other.id)
        await register_outbound_servers(self.context)
        proxies = (await self.core.rest_client.get_proxies())["proxies"]
        # The main route is connected again; the test route stays blocked.
        self.assertEqual(proxies["main"]["now"], server.id)
        self.assertEqual(proxies["test"]["now"], "REJECT")
        # Traffic of the main listener goes through the connected server.
        base = f"http://127.0.0.1:{self.http_port}"
        connector = ProxyConnector.from_url(f"socks5://127.0.0.1:{self.core.proxy_port}")
        async with (
            ClientSession(connector=connector) as session,
            session.get(f"{base}/status/204") as response,
        ):
            self.assertEqual(response.status, 204)

    async def test_unreachable_server(self):
        self.context.settings.server_settings.save(
            ServerSettings(
                outbound_tests=(
                    outbound_test("a", "http://127.0.0.1/", OutboundTestRule.ANY_STATUS),
                )
            )
        )
        dead = vless(free_port())
        self.context.settings.outbound_server.save(dead)
        await self.core.outbound_register([dead])
        updated = await handler.test_outbound(self.context, dead)
        assert updated is not None
        self.assertEqual(
            (updated.ping, updated.speed, updated.rating, updated.tests),
            (None, None, 0, {"a": False}),
        )
        self.assertEqual(self.requests, [])
