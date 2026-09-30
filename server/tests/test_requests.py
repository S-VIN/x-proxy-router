import asyncio
import json
import unittest
from contextlib import chdir
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from server.cores.core_client import CoreClient
from server.handlers.subscriptions import refresh_subscriptions
from server.main import WebSocketServer, application, configure_handlers
from server.models import (
    FilterReason,
    OutboundProtocol,
    OutboundServer,
    OutboundTestRule,
    RegFilter,
    SubscriptionLink,
    serialize,
)
from server.request_error import ErrorCode, RequestError
from server.subscription_loader import SubscriptionError
from server.tests.support import startup_finished

URL = "https://user:token@sub.example.com/secret-path"


def servers_of(link: SubscriptionLink) -> list[OutboundServer]:
    return [
        OutboundServer(
            name=link.url_short,
            address="example.com",
            port=443,
            subscription_id=link.id,
            protocol=OutboundProtocol.HYSTERIA,
            hysteria_auth="auth",
        )
    ]


class Client:
    """Records frames the way a transport would receive them."""

    def __init__(self, websocket: WebSocketServer, connection_id: str = "client"):
        self.websocket = websocket
        self.connection_id = connection_id
        self.frames: list[dict] = []
        # "task" messages queued before the last response, kept out of its updates.
        self.task_updates: list[dict] = []
        self.received = asyncio.Event()
        websocket.connect(connection_id, self._send)

    async def _send(self, frame: str) -> None:
        self.frames.append(json.loads(frame))
        self.received.set()

    async def response(self) -> tuple[list[dict], dict]:
        """Wait for the next response; return it with the messages queued before it."""
        async with asyncio.timeout(2):
            while not any(frame["type"] == "response" for frame in self.frames):
                self.received.clear()
                await self.received.wait()
        index = next(i for i, frame in enumerate(self.frames) if frame["type"] == "response")
        before, response = self.frames[:index], self.frames[index]
        self.frames = self.frames[index + 1 :]
        self.task_updates = [frame for frame in before if frame["model"] == "task"]
        return [frame for frame in before if frame["model"] != "task"], response

    async def request(
        self, request_type: str, model: str, payload: object, request_id: str = "r1"
    ) -> tuple[list[dict], dict]:
        message = {"type": request_type, "model": model, "request_id": request_id}
        self.websocket.receive(self.connection_id, json.dumps({**message, "payload": payload}))
        return await self.response()

    async def error(self, request_type: str, model: str, payload: object) -> dict:
        _, response = await self.request(request_type, model, payload)
        self.assert_error(response)
        return response["error"]

    @staticmethod
    def assert_error(response: dict) -> None:
        assert response["ok"] is False and response["payload"] == {}, response


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.core = AsyncMock(spec=CoreClient)
        self.enterContext(patch("server.main.MihomoClient", return_value=self.core))
        self.load = self.enterContext(
            patch("server.handlers.subscriptions.load_subscription", new=AsyncMock(return_value=[]))
        )
        self.context = await self.enterAsyncContext(application())
        configure_handlers(self.context)
        self.client = Client(self.context.websocket)
        # Skip the initial snapshots.
        async with asyncio.timeout(2):
            while len(self.client.frames) < 6:
                self.client.received.clear()
                await self.client.received.wait()
        await startup_finished(self.context)
        self.client.frames.clear()

    async def test_subscription_link_lifecycle(self):
        updates, response = await self.client.request("add", "subscription_link", {"url": URL})
        link_id = response["payload"]["id"]
        self.assertEqual(
            response,
            {
                "type": "response",
                "model": "subscription_link",
                "request_id": "r1",
                "ok": True,
                "payload": {"id": link_id},
            },
        )
        # The change arrives before the response, so the client already has the object.
        # The refresh after adding loads no servers here but records its time.
        self.assertEqual(
            [update["model"] for update in updates], ["subscription_link", "server_settings"]
        )
        update = updates[0]
        self.assertEqual(
            update["payload"], [{"id": link_id, "url_short": "https://sub.example.com"}]
        )
        self.assertNotIn("token", json.dumps(update))
        self.assertEqual(self.context.settings.subscription_link.get_all()[0].url, URL)

        new_url = "https://other.example.com/token"
        updates, response = await self.client.request(
            "change", "subscription_link", {"id": link_id, "url": new_url}
        )
        self.assertEqual((response["ok"], response["payload"]), (True, {}))
        self.assertEqual(updates[0]["payload"][0]["url_short"], "https://other.example.com")
        [changed] = self.context.settings.subscription_link.get_all()
        self.assertEqual((changed.id, changed.url), (link_id, new_url))

        updates, response = await self.client.request(
            "delete", "subscription_link", {"id": link_id}
        )
        self.assertTrue(response["ok"])
        self.assertEqual((updates[0]["payload"], updates[0]["deleted_ids"]), ([], [link_id]))
        self.assertEqual(self.context.settings.subscription_link.get_all(), [])

    async def test_add_loads_servers_before_responding(self):
        self.load.side_effect = servers_of
        updates, response = await self.client.request("add", "subscription_link", {"url": URL})
        self.assertTrue(response["ok"])
        link_id = response["payload"]["id"]
        self.assertEqual(
            [update["model"] for update in updates],
            ["subscription_link", "outbound_server", "server_settings"],
        )
        [server] = updates[1]["payload"]
        self.assertEqual(
            (server["subscription_id"], server["name"]), (link_id, "https://sub.example.com")
        )
        [stored] = self.context.settings.outbound_server.get_all()
        self.assertEqual(stored.subscription_id, link_id)

    async def test_add_keeps_link_when_loading_fails(self):
        old = SubscriptionLink(url="https://old.example.com/sub")
        self.context.settings.subscription_link.save(old)
        self.context.settings.outbound_server.update_servers(servers_of(old))

        async def load(link):
            if link.id != old.id:
                raise SubscriptionError(link.id)
            return servers_of(link)

        self.load.side_effect = load
        updates, response = await self.client.request("add", "subscription_link", {"url": URL})
        Client.assert_error(response)
        [link, _] = self.context.settings.subscription_link.get_all()[::-1]
        self.assertEqual(
            response["error"],
            {
                "code": "subscription_error",
                "message": "The subscription link was added, but subscriptions could not be loaded",
                "details": {"id": link.id, "failed_id": link.id},
            },
        )
        # The client still learns about the saved link; servers stay as they were.
        self.assertEqual([update["model"] for update in updates], ["subscription_link"])
        self.assertEqual(
            [server.subscription_id for server in self.context.settings.outbound_server.get_all()],
            [old.id],
        )

    async def test_refresh_started_earlier_cannot_drop_added_servers(self):
        old = SubscriptionLink(url="https://old.example.com/sub")
        self.context.settings.subscription_link.save(old)
        loading, release = asyncio.Event(), asyncio.Event()

        async def load(link):
            # Only the earlier refresh is slow; the add's own refresh loads at once.
            if not loading.is_set():
                loading.set()
                await release.wait()
            return servers_of(link)

        self.load.side_effect = load
        # Like the startup refresh: it has read the links before the new one is added.
        earlier = asyncio.create_task(refresh_subscriptions(self.context))
        await loading.wait()
        self.client.websocket.receive(
            "client",
            json.dumps(
                {
                    "type": "add",
                    "model": "subscription_link",
                    "request_id": "r1",
                    "payload": {"url": URL},
                }
            ),
        )
        for _ in range(5):
            await asyncio.sleep(0)
        release.set()
        _, response = await self.client.response()
        await earlier
        self.assertTrue(response["ok"])
        self.assertEqual(
            [server.subscription_id for server in self.context.settings.outbound_server.get_all()],
            [old.id, response["payload"]["id"]],
        )

    async def test_refresh_request_reloads_servers_and_records_time(self):
        link = SubscriptionLink(url=URL)
        self.context.settings.subscription_link.save(link)
        self.load.side_effect = servers_of
        before = datetime.now(UTC)
        updates, response = await self.client.request("request", "refresh_subscriptions", {})
        self.assertEqual(
            response,
            {
                "type": "response",
                "model": "refresh_subscriptions",
                "request_id": "r1",
                "ok": True,
                "payload": {},
            },
        )
        self.assertEqual(
            [update["model"] for update in updates], ["outbound_server", "server_settings"]
        )
        # The refresh is a long task: clients see it start and finish before the response.
        self.assertEqual(
            [update["payload"] for update in self.client.task_updates],
            [
                [{"id": "refresh_subscriptions", "status": "running"}],
                [{"id": "refresh_subscriptions", "status": "stopped"}],
            ],
        )
        self.assertEqual(updates[0]["payload"][0]["subscription_id"], link.id)
        refreshed = self.context.settings.server_settings.get().last_subscription_refresh
        assert refreshed is not None
        self.assertLessEqual(before, refreshed)
        self.assertEqual(
            updates[1]["payload"][0]["last_subscription_refresh"],
            refreshed.isoformat().replace("+00:00", "Z"),
        )

        # Unchanged servers produce no outbound_server message, only the new time.
        updates, response = await self.client.request("request", "refresh_subscriptions", {})
        self.assertTrue(response["ok"])
        self.assertEqual([update["model"] for update in updates], ["server_settings"])

    async def test_refresh_request_failure_keeps_servers_and_time(self):
        link = SubscriptionLink(url=URL)
        self.context.settings.subscription_link.save(link)
        self.context.settings.outbound_server.update_servers(servers_of(link))
        # Set by the successful startup refresh in asyncSetUp.
        before = self.context.settings.server_settings.get().last_subscription_refresh
        self.assertIsNotNone(before)

        async def fail(link):
            raise SubscriptionError(link.id)

        self.load.side_effect = fail
        updates, response = await self.client.request("request", "refresh_subscriptions", {})
        Client.assert_error(response)
        self.assertEqual(
            response["error"],
            {
                "code": "subscription_error",
                "message": "Subscriptions could not be loaded",
                "details": {"failed_id": link.id},
            },
        )
        self.assertEqual(updates, [])
        self.assertEqual(len(self.context.settings.outbound_server.get_all()), 1)
        self.assertEqual(
            self.context.settings.server_settings.get().last_subscription_refresh, before
        )

        error = await self.client.error("request", "refresh_subscriptions", {"id": link.id})
        self.assertEqual((error["code"], error["details"]), ("bad_request", {"field": "id"}))
        self.load.assert_awaited_once()

    async def check_servers(self) -> list[OutboundServer]:
        """Store two servers and mock network checks; each server passes."""
        servers = [
            OutboundServer(
                name=name,
                address="example.com",
                port=443,
                protocol=OutboundProtocol.HYSTERIA,
                hysteria_auth="auth",
            )
            for name in ("one", "two")
        ]
        self.context.settings.outbound_server.add_servers(servers)
        await self.context.sync.notify("outbound_server")
        for _ in range(5):
            await asyncio.sleep(0)  # Let the writer send the change.
        self.client.frames.clear()
        self.core.test_port = 1080
        for name, value in (("download_speed", 125_000), ("run_test", True)):
            self.enterContext(
                patch(f"server.handlers.outbound_test.{name}", AsyncMock(return_value=value))
            )
        return servers

    async def test_test_outbound_servers_reports_each_server(self):
        first, second = await self.check_servers()
        updates, response = await self.client.request("request", "test_outbound_servers", {})
        self.assertTrue(response["ok"])
        self.assertEqual(response["payload"], {})
        # One message per checked server, sent as soon as it is checked.
        self.assertEqual(
            [[server["id"] for server in update["payload"]] for update in updates],
            [[first.id], [second.id]],
        )
        self.assertEqual(updates[1]["payload"][0]["rating"], 100)
        self.assertEqual(
            [update["payload"] for update in self.client.task_updates],
            [
                [{"id": "test_outbound_servers", "status": "running"}],
                [{"id": "test_outbound_servers", "status": "stopped"}],
            ],
        )
        error = await self.client.error("request", "test_outbound_servers", {"id": first.id})
        self.assertEqual((error["code"], error["details"]), ("bad_request", {"field": "id"}))

    async def test_test_outbound_servers_conflicts_with_refresh(self):
        await self.check_servers()
        self.context.settings.subscription_link.save(SubscriptionLink(url=URL))
        loading, finish = asyncio.Event(), asyncio.Event()

        async def load(link):
            loading.set()
            await finish.wait()
            return []

        self.load.side_effect = load
        refresh = asyncio.create_task(refresh_subscriptions(self.context))
        await loading.wait()
        error = await self.client.error("request", "test_outbound_servers", {})
        self.assertEqual(error["code"], "conflict")
        self.core.test_connect.assert_not_awaited()
        finish.set()
        await refresh

    async def test_connect_outbound_server(self):
        first, second = await self.check_servers()
        core = self.core
        updates, response = await self.client.request(
            "request", "connect_outbound_server", {"id": second.id}
        )
        self.assertTrue(response["ok"])
        core.outbound_connect.assert_awaited_once_with(second.id)
        [update] = updates
        self.assertEqual(
            [(server["id"], server["is_connected"]) for server in update["payload"]],
            [(second.id, True)],
        )
        core.outbound_connect.side_effect = RuntimeError(URL)
        with self.assertLogs("server.handlers.core", level="ERROR"):
            error = await self.client.error("request", "connect_outbound_server", {"id": first.id})
        self.assertEqual(
            error,
            {
                "code": "core_error",
                "message": "The core could not connect to the server",
                "details": {"id": first.id},
            },
        )
        cases = [
            ({"id": "missing"}, "not_found", {"field": "id"}),
            ({}, "bad_request", {"field": "id"}),
            ({"id": 1}, "bad_request", {"field": "id"}),
        ]
        for payload, code, details in cases:
            with self.subTest(payload=payload):
                error = await self.client.error("request", "connect_outbound_server", payload)
                self.assertEqual((error["code"], error["details"]), (code, details))
        connected = self.context.settings.outbound_server.get_connected()
        assert connected is not None
        self.assertEqual(connected.id, second.id)
        self.assertEqual(self.client.frames, [])

    async def test_connect_to_a_filtered_server_conflicts(self):
        first, second = await self.check_servers()
        await self.client.request("request", "connect_outbound_server", {"id": first.id})
        self.context.settings.reg_filter.add(RegFilter(reg="^two$"))
        error = await self.client.error("request", "connect_outbound_server", {"id": second.id})
        self.assertEqual(
            error,
            {
                "code": "conflict",
                "message": "Filtered servers cannot be connected",
                "details": {"id": second.id},
            },
        )
        self.core.outbound_connect.assert_awaited_once_with(first.id)

    async def test_reg_filter_lifecycle(self):
        _, second = await self.check_servers()
        servers = self.context.settings.outbound_server
        updates, response = await self.client.request("add", "reg_filter", {"reg": "^two$"})
        filter_id = response["payload"]["id"]
        self.assertEqual(
            (response["model"], response["ok"], response["payload"]),
            ("reg_filter", True, {"id": filter_id}),
        )
        self.assertEqual(
            [server.filtered for server in servers.get_all()], [None, FilterReason.BY_REG_FILTER]
        )
        # The filter and only the servers it matches reach clients before the response.
        self.assertEqual(
            [(update["model"], update["payload"]) for update in updates],
            [
                ("reg_filter", [{"id": filter_id, "reg": "^two$"}]),
                ("outbound_server", [serialize(servers.get_by_id(second.id))]),
            ],
        )
        updates, response = await self.client.request("delete", "reg_filter", {"id": filter_id})
        self.assertEqual((response["ok"], response["payload"]), (True, {}))
        self.assertEqual([server.filtered for server in servers.get_all()], [None, None])
        self.assertEqual(
            [(update["model"], update["payload"], update["deleted_ids"]) for update in updates],
            [
                ("reg_filter", [], [filter_id]),
                ("outbound_server", [serialize(servers.get_by_id(second.id))], []),
            ],
        )
        self.assertEqual(self.context.settings.reg_filter.get_all(), [])

    async def test_filter_on_the_connected_server_disconnects_it(self):
        first, _ = await self.check_servers()
        await self.client.request("request", "connect_outbound_server", {"id": first.id})
        updates, response = await self.client.request("add", "reg_filter", {"reg": "^one$"})
        self.assertTrue(response["ok"])
        # The mode was off, so only the server changes: filtered and disconnected at once.
        self.assertEqual([update["model"] for update in updates], ["reg_filter", "outbound_server"])
        self.assertEqual(
            [
                (server["id"], server["filtered"], server["is_connected"])
                for server in updates[1]["payload"]
            ],
            [(first.id, "by_reg_filter", False)],
        )
        self.core.outbound_disconnect.assert_awaited_once_with()
        # Deleting the filter does not connect the server again.
        updates, _ = await self.client.request(
            "delete", "reg_filter", {"id": response["payload"]["id"]}
        )
        self.assertEqual(
            [
                (server["id"], server["filtered"], server["is_connected"])
                for server in updates[1]["payload"]
            ],
            [(first.id, None, False)],
        )
        self.assertIsNone(self.context.settings.outbound_server.get_connected())

    async def test_reg_filter_errors(self):
        existing = RegFilter(reg="^RU")
        self.context.settings.reg_filter.add(existing)
        cases = [
            ("add", {"reg": "^RU"}, "conflict", {"field": "reg"}),
            ("add", {"reg": ""}, "validation_error", {"field": "reg"}),
            ("add", {"reg": "("}, "validation_error", {"field": "reg"}),
            ("add", {"reg": 1}, "bad_request", {"field": "reg"}),
            ("add", {}, "bad_request", {"field": "reg"}),
            ("add", {"reg": "NL", "id": "mine"}, "bad_request", {"field": "id"}),
            ("delete", {"id": "missing"}, "not_found", {"field": "id"}),
            ("delete", {}, "bad_request", {"field": "id"}),
        ]
        for request_type, payload, code, details in cases:
            with self.subTest(request_type=request_type, payload=payload):
                error = await self.client.error(request_type, "reg_filter", payload)
                self.assertEqual((error["code"], error["details"]), (code, details))
        self.assertEqual(self.context.settings.reg_filter.get_all(), [existing])
        self.assertEqual(self.client.frames, [])
        error = await self.client.error("change", "reg_filter", {"id": existing.id, "reg": "x"})
        self.assertEqual(error["code"], "unknown_request")

    async def test_subscription_link_errors(self):
        existing = SubscriptionLink(url=URL)
        self.context.settings.subscription_link.save(existing)
        cases = [
            ("add", {"url": URL}, "conflict", {"field": "url"}),
            ("add", {"url": "ftp://example.com"}, "validation_error", {}),
            ("add", {"url": 1}, "bad_request", {"field": "url"}),
            ("add", {}, "bad_request", {"field": "url"}),
            ("add", {"url": URL, "id": "mine"}, "bad_request", {"field": "id"}),
            ("change", {"id": "missing", "url": URL}, "not_found", {"field": "id"}),
            (
                "change",
                {"id": existing.id, "url_short": "x"},
                "bad_request",
                {"field": "url_short"},
            ),
            ("delete", {"id": "missing"}, "not_found", {"field": "id"}),
        ]
        for request_type, payload, code, details in cases:
            with self.subTest(request_type=request_type, payload=payload):
                error = await self.client.error(request_type, "subscription_link", payload)
                self.assertEqual((error["code"], error["details"]), (code, details))
                self.assertNotIn("token", json.dumps(error))
        self.assertEqual(self.context.settings.subscription_link.get_all(), [existing])
        # Failed requests change nothing, so clients receive no updates.
        self.assertEqual(self.client.frames, [])

    async def test_server_settings(self):
        updates, response = await self.client.request(
            "change", "server_settings", {"id": 0, "subscription_refresh_interval": 600}
        )
        self.assertTrue(response["ok"])
        self.assertEqual(updates[0]["payload"][0]["subscription_refresh_interval"], 600)
        self.assertEqual(
            self.context.settings.server_settings.get().subscription_refresh_interval, 600
        )
        cases = [
            ({"id": 0, "subscription_refresh_interval": 0}, "validation_error"),
            ({"id": 0, "subscription_refresh_interval": True}, "bad_request"),
            ({"id": 0, "last_subscription_refresh": "2026-09-26T12:00:00Z"}, "bad_request"),
            ({"id": 1}, "not_found"),
            ({"id": "0"}, "bad_request"),
        ]
        for payload, code in cases:
            with self.subTest(payload=payload):
                error = await self.client.error("change", "server_settings", payload)
                self.assertEqual(error["code"], code)
        error = await self.client.error("delete", "server_settings", {"id": 0})
        self.assertEqual(error["code"], "unknown_request")
        self.assertEqual(
            self.context.settings.server_settings.get().subscription_refresh_interval, 600
        )

    async def test_new_interval_restarts_the_refresh_timer(self):
        scheduler = self.context.scheduler

        def job():
            found = scheduler.get_job("refresh_subscriptions")
            assert found is not None
            return found

        self.assertEqual(job().trigger.interval, timedelta(days=1))
        await self.client.request(
            "change", "server_settings", {"id": 0, "subscription_refresh_interval": 600}
        )
        self.assertEqual(job().trigger.interval, timedelta(seconds=600))
        next_run = job().next_run_time
        self.assertLessEqual(next_run, datetime.now(UTC) + timedelta(seconds=600))
        # Other changes, and the same interval again, keep the timer running.
        await self.client.request("change", "server_settings", {"id": 0, "outbound_tests": []})
        await self.client.request(
            "change", "server_settings", {"id": 0, "subscription_refresh_interval": 600}
        )
        self.assertEqual(job().next_run_time, next_run)
        # A rejected value changes nothing.
        await self.client.error(
            "change", "server_settings", {"id": 0, "subscription_refresh_interval": 0}
        )
        self.assertEqual(job().trigger.interval, timedelta(seconds=600))

    async def test_server_settings_outbound_tests(self):
        google = {
            "url": "https://www.gstatic.com/generate_204",
            "alias": "google",
            "rule": "status_204",
        }
        site = {"url": "https://example.com/", "alias": "site", "rule": "status_below_503"}
        updates, response = await self.client.request(
            "change", "server_settings", {"id": 0, "outbound_tests": [google, site]}
        )
        self.assertTrue(response["ok"])
        self.assertEqual(updates[0]["payload"][0]["outbound_tests"], [google, site])
        stored = self.context.settings.server_settings.get()
        self.assertEqual([test.alias for test in stored.outbound_tests], ["google", "site"])
        self.assertIs(stored.outbound_tests[1].rule, OutboundTestRule.STATUS_BELOW_503)
        cases = [
            ({"outbound_tests": {}}, "bad_request", "outbound_tests"),
            ({"outbound_tests": [google, "x"]}, "bad_request", "outbound_tests[1]"),
            (
                {"outbound_tests": [{"url": google["url"], "alias": "a"}]},
                "bad_request",
                "outbound_tests[0].rule",
            ),
            (
                {"outbound_tests": [{**google, "id": 1}]},
                "bad_request",
                "outbound_tests[0].id",
            ),
            (
                {"outbound_tests": [{**google, "alias": 1}]},
                "bad_request",
                "outbound_tests[0].alias",
            ),
            (
                {"outbound_tests": [google, {**site, "rule": "status_below_42"}]},
                "validation_error",
                "outbound_tests[1].rule",
            ),
            (
                {"outbound_tests": [{**google, "url": "ftp://example.com"}]},
                "validation_error",
                "outbound_tests[0]",
            ),
        ]
        for changes, code, field in cases:
            with self.subTest(changes=changes):
                error = await self.client.error("change", "server_settings", {"id": 0, **changes})
                self.assertEqual((error["code"], error["details"]), (code, {"field": field}))
        error = await self.client.error(
            "change",
            "server_settings",
            {"id": 0, "outbound_tests": [google, {**site, "alias": "google"}]},
        )
        self.assertEqual(error["code"], "validation_error")
        self.assertEqual(self.context.settings.server_settings.get(), stored)
        # An empty list removes all tests; other settings are kept.
        await self.client.request("change", "server_settings", {"id": 0, "outbound_tests": []})
        self.assertEqual(
            self.context.settings.server_settings.get(), replace(stored, outbound_tests=())
        )

    async def test_auto_connect(self):
        first, second = await self.check_servers()
        servers = self.context.settings.outbound_server
        for server, rating in ((first, 60), (second, 90)):
            servers.update_health(
                server.id, ping=None, speed=None, rating=rating, tests={}, filtered=None
            )
        await self.context.sync.notify("outbound_server")
        for _ in range(5):
            await asyncio.sleep(0)  # Let the writer send the change.
        self.client.frames.clear()

        def connections(update: dict) -> list[tuple[str, bool]]:
            return [(server["id"], server["is_connected"]) for server in update["payload"]]

        # Turned on, the mode reaches clients first, then the best server is connected.
        updates, response = await self.client.request(
            "change", "server_settings", {"id": 0, "auto_connect": True}
        )
        self.assertTrue(response["ok"])
        self.assertEqual(
            [update["model"] for update in updates], ["server_settings", "outbound_server"]
        )
        self.assertIs(updates[0]["payload"][0]["auto_connect"], True)
        self.assertEqual(connections(updates[1]), [(second.id, True)])
        # A server chosen by a client turns the mode off.
        updates, response = await self.client.request(
            "request", "connect_outbound_server", {"id": first.id}
        )
        self.assertTrue(response["ok"])
        self.assertEqual(
            [update["model"] for update in updates], ["server_settings", "outbound_server"]
        )
        self.assertIs(updates[0]["payload"][0]["auto_connect"], False)
        self.assertEqual(connections(updates[1]), [(first.id, True), (second.id, False)])
        # On again: back to the best server. Turning the mode off changes only the setting.
        await self.client.request("change", "server_settings", {"id": 0, "auto_connect": True})
        updates, _ = await self.client.request(
            "change", "server_settings", {"id": 0, "auto_connect": False}
        )
        self.assertEqual([update["model"] for update in updates], ["server_settings"])
        # A filter on the connected server disconnects it and turns the mode off.
        await self.client.request("change", "server_settings", {"id": 0, "auto_connect": True})
        updates, _ = await self.client.request("add", "reg_filter", {"reg": "^two$"})
        self.assertEqual(
            [update["model"] for update in updates],
            ["reg_filter", "server_settings", "outbound_server"],
        )
        self.assertIs(updates[1]["payload"][0]["auto_connect"], False)
        self.assertEqual(
            [
                (server["id"], server["filtered"], server["is_connected"])
                for server in updates[2]["payload"]
            ],
            [(second.id, "by_reg_filter", False)],
        )
        self.assertIsNone(servers.get_connected())
        self.core.outbound_disconnect.assert_awaited_once_with()
        self.assertEqual(
            [call.args[0] for call in self.core.outbound_connect.await_args_list],
            [second.id, first.id, second.id],
        )
        for value in (1, "true", None):
            with self.subTest(auto_connect=value):
                error = await self.client.error(
                    "change", "server_settings", {"id": 0, "auto_connect": value}
                )
                self.assertEqual(
                    (error["code"], error["details"]), ("bad_request", {"field": "auto_connect"})
                )
        self.assertFalse(self.context.settings.server_settings.get().auto_connect)

    async def test_malformed_messages(self):
        websocket = self.context.websocket
        frames = {
            "not json": (None, None),
            "[]": (None, None),
            json.dumps({"type": "add", "model": "subscription_link", "payload": {}}): (
                None,
                "subscription_link",
            ),
            json.dumps({"type": "add", "request_id": "r7", "payload": {}}): ("r7", None),
            json.dumps(
                {"type": "add", "model": "subscription_link", "request_id": "r8", "payload": []}
            ): ("r8", "subscription_link"),
        }
        for frame, (request_id, model) in frames.items():
            with self.subTest(frame=frame):
                websocket.receive("client", frame)
                _, response = await self.client.response()
                Client.assert_error(response)
                self.assertEqual(response["error"]["code"], "bad_request")
                self.assertEqual((response["request_id"], response["model"]), (request_id, model))
        with self.assertRaises(KeyError):
            websocket.receive("missing", "{}")


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.websocket = WebSocketServer()
        self.client = Client(self.websocket)

    async def asyncTearDown(self):
        await self.websocket.close()

    async def test_internal_errors_are_logged_but_not_sent(self):
        async def failing(payload):
            raise RuntimeError(URL)

        self.websocket.register("refresh", "example", failing)
        with self.assertLogs("server.main", level="ERROR") as logs:
            error = await self.client.error("refresh", "example", {})
        self.assertEqual(
            error, {"code": "internal_error", "message": "Internal server error", "details": {}}
        )
        self.assertIn("RuntimeError", "\n".join(logs.output))

    async def test_request_error_is_sent_as_is(self):
        async def rejecting(payload):
            raise RequestError(ErrorCode.CONFLICT, "Busy", {"field": "x"})

        self.websocket.register("refresh", "example", rejecting)
        error = await self.client.error("refresh", "example", {})
        self.assertEqual(error, {"code": "conflict", "message": "Busy", "details": {"field": "x"}})

    async def test_slow_request_does_not_block_others(self):
        release = asyncio.Event()

        async def slow(payload):
            await release.wait()
            return {"done": "slow"}

        async def fast(payload):
            return {"done": "fast"}

        self.websocket.register("refresh", "slow", slow)
        self.websocket.register("refresh", "fast", fast)
        self.websocket.receive(
            "client",
            json.dumps({"type": "refresh", "model": "slow", "request_id": "1", "payload": {}}),
        )
        _, response = await self.client.request("refresh", "fast", {}, request_id="2")
        self.assertEqual((response["request_id"], response["payload"]), ("2", {"done": "fast"}))
        release.set()
        _, response = await self.client.response()
        self.assertEqual((response["request_id"], response["payload"]), ("1", {"done": "slow"}))

    async def test_disconnect_drops_response_and_close_cancels_requests(self):
        started, finished, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        release = asyncio.Event()

        async def slow(payload):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            finished.set()
            return {}

        self.websocket.register("refresh", "slow", slow)
        message = {"type": "refresh", "model": "slow", "request_id": "1", "payload": {}}
        self.websocket.receive("client", json.dumps(message))
        await started.wait()
        await self.websocket.disconnect("client")
        release.set()
        async with asyncio.timeout(2):
            await finished.wait()
        self.assertEqual(self.client.frames, [])

        release.clear()
        started.clear()
        Client(self.websocket, "other")
        self.websocket.receive("other", json.dumps(message))
        await started.wait()
        await self.websocket.close()
        self.assertTrue(cancelled.is_set())
