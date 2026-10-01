import unittest
from contextlib import chdir
from dataclasses import replace
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from server.cores.core_client import CoreClient
from server.handlers import auto_connect
from server.handlers.auto_connect import (
    CANDIDATE_QUARANTINE,
    CHECK_INTERVAL,
    DAILY_SWITCHES,
    DAY,
    DEGRADED_DROP,
    FAILED_CHECKS,
    MARGIN,
    MAX_QUARANTINE,
    MIN_STAY_DEGRADED,
    MIN_STAY_IMPROVEMENT,
    QUARANTINE,
    REACHABILITY_TEST,
    RETRY_INTERVAL,
    on_auto_connect_enabled,
    on_check_run_finished,
    on_servers_changed,
    watch_connected_server,
)
from server.handlers.core import connect_outbound_server
from server.handlers.server_settings import change_server_settings
from server.handlers.subscriptions import refresh_subscriptions
from server.main import application
from server.models import (
    FilterReason,
    OutboundServer,
    OutboundTest,
    OutboundTestRule,
    RegFilter,
    ServerSettings,
    SubscriptionLink,
)
from server.settings_store import SettingsStore
from server.tests.support import startup_finished
from server.tests.test_connection import ConnectionTestCase, vless
from server.tests.test_model_sync import Client

# Outcome of a quick check: passes with the stored rating (True) or this rating,
# fails (False), or the check itself raises.
Outcome = bool | int | Exception


class AutoConnectTestCase(ConnectionTestCase):
    """Servers one and two, none connected; the clock and quick checks are fakes."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.now = 1000.0
        self.enterContext(patch.object(auto_connect, "monotonic", lambda: self.now))
        # Server id -> outcome of its quick checks; passes by default.
        self.quick: dict[str, Outcome] = {}
        self.quick_checked: list[str] = []
        self.enterContext(patch.object(auto_connect, "quick_test_outbound", self.quick_test))
        self.state = self.context.auto_connect

    async def quick_test(
        self, context, server: OutboundServer, tests: tuple[OutboundTest, ...]
    ) -> OutboundServer:
        self.quick_checked.append(server.id)
        outcome = self.quick.get(server.id, True)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is False:
            return replace(server, tests=dict.fromkeys((test.alias for test in tests), False))
        rating = server.rating if outcome is True else outcome
        return replace(
            server, rating=rating, tests=dict.fromkeys((test.alias for test in tests), True)
        )

    def rate(
        self, server: OutboundServer, rating: int, filtered: FilterReason | None = None
    ) -> None:
        self.store.update_health(
            server.id, ping=None, speed=None, rating=rating, tests={}, filtered=filtered
        )

    def set_auto_connect(self, enabled: bool) -> None:
        settings = self.context.settings.server_settings
        settings.save(replace(settings.get(), auto_connect=enabled))

    async def enable(self) -> None:
        self.set_auto_connect(True)
        await on_auto_connect_enabled(self.context)

    async def run_finished(self) -> None:
        """A check run that rated every server as stored."""
        await on_check_run_finished(self.context, self.store.get_all())

    async def tick(self, seconds: float = 0) -> None:
        """Move the clock, then run the watch job."""
        self.now += seconds
        await watch_connected_server(self.context)

    def connected_id(self) -> str | None:
        connected = self.store.get_connected()
        return connected.id if connected is not None else None

    def connections(self) -> list[str]:
        return [call.args[0] for call in self.core.outbound_connect.await_args_list]

    def forget_calls(self) -> None:
        self.quick_checked.clear()
        self.core.reset_mock()


class ChoiceTests(AutoConnectTestCase):
    async def test_best_server_that_may_be_connected(self):
        named, no_ping, unchecked, zero = (vless(name) for name in ("3", "4", "5", "6"))
        self.store.add_servers([named, no_ping, unchecked, zero])
        self.rate(self.first, 50)
        self.rate(self.second, 90)
        self.rate(named, 100)
        self.rate(no_ping, 95, FilterReason.BY_PING)
        self.rate(zero, 0)
        self.context.settings.reg_filter.add(RegFilter(reg="3"))
        # The mode is off by default.
        await on_servers_changed(self.context)
        await self.tick()
        self.assertEqual(self.quick_checked, [])
        client = Client(self.context.websocket)
        await client.messages()
        await self.enable()
        self.assertEqual(self.quick_checked, [self.second.id])
        self.assertEqual(self.connections(), [self.second.id])
        [message] = await client.messages()
        self.assertEqual(message["model"], "outbound_server")

    async def test_servers_are_checked_before_connecting(self):
        third = vless("three")
        self.store.add_servers([third])
        for server, rating in ((self.first, 90), (self.second, 80), (third, 70)):
            self.rate(server, rating)
        self.quick[self.first.id] = False
        await self.enable()
        # The best server failed its check: the next one is connected, the failed one waits.
        self.assertEqual(self.quick_checked, [self.first.id, self.second.id])
        self.assertEqual(self.connected_id(), self.second.id)
        self.assertEqual(self.state.quarantine, {self.first.id: self.now + CANDIDATE_QUARANTINE})
        self.quick.clear()
        for waited, expected in ((CANDIDATE_QUARANTINE - 1, self.second.id), (1, self.first.id)):
            self.store.set_connected(None)
            self.now += waited
            await on_servers_changed(self.context)
            self.assertEqual(self.connected_id(), expected)

    async def test_nothing_changes_when_no_server_passes(self):
        third, fourth = vless("three"), vless("four")
        self.store.add_servers([third, fourth])
        for server, rating in ((self.first, 90), (self.second, 80), (third, 70), (fourth, 60)):
            self.rate(server, rating)
            self.quick[server.id] = False
        await self.enable()
        # At most three are tried. None works, so the router's own connection is
        # taken to be down: nobody is quarantined.
        self.assertEqual(self.quick_checked, [self.first.id, self.second.id, third.id])
        self.core.outbound_connect.assert_not_awaited()
        self.assertEqual(self.state.quarantine, {})
        # The watch tries again after CHECK_INTERVAL.
        self.quick.clear()
        await self.tick(CHECK_INTERVAL - 1)
        self.core.outbound_connect.assert_not_awaited()
        await self.tick(1)
        self.assertEqual(self.connected_id(), self.first.id)

    async def test_core_failure_tries_the_next_server(self):
        self.rate(self.first, 90)
        self.rate(self.second, 80)

        def connect(server_id):
            if server_id == self.first.id:
                raise RuntimeError("not registered")

        self.core.outbound_connect.side_effect = connect
        with self.assertLogs("server.handlers.core", level="ERROR"):
            await self.enable()
        self.assertEqual(self.connected_id(), self.second.id)
        self.assertIn(self.first.id, self.state.quarantine)

    async def test_enabling_keeps_the_connected_server_unless_one_is_margin_ahead(self):
        self.rate(self.first, 80)
        self.rate(self.second, 80 + MARGIN - 1)
        await connect_outbound_server(self.context, self.first.id)
        await self.enable()
        self.assertEqual(self.connected_id(), self.first.id)
        self.set_auto_connect(False)
        self.rate(self.second, 80 + MARGIN)
        await self.enable()
        self.assertEqual(self.connected_id(), self.second.id)
        # The choice made on enabling does not count towards the daily limit.
        self.assertEqual(self.state.switches, [])
        # A connected server filtered by ping gives way to any.
        self.set_auto_connect(False)
        self.rate(self.first, 20)
        self.rate(self.second, 90, FilterReason.BY_PING)
        await self.enable()
        self.assertEqual(self.connected_id(), self.first.id)
        # Turning the mode on when it is on already changes nothing.
        self.forget_calls()
        await change_server_settings(self.context, {"id": 0, "auto_connect": True})
        self.assertEqual(self.quick_checked, [])
        self.core.outbound_connect.assert_not_awaited()


class FailureTests(AutoConnectTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.rate(self.first, 90)
        self.rate(self.second, 80)
        await self.enable()
        self.assertEqual(self.connected_id(), self.first.id)
        self.forget_calls()

    async def test_server_is_replaced_after_failed_checks(self):
        self.quick[self.first.id] = False
        # The first check is CHECK_INTERVAL after connecting, the next ones sooner.
        await self.tick(CHECK_INTERVAL - 1)
        self.assertEqual(self.quick_checked, [])
        await self.tick(1)
        await self.tick(RETRY_INTERVAL - 1)
        self.assertEqual(self.quick_checked, [self.first.id])
        await self.tick(1)
        self.assertEqual(self.quick_checked, [self.first.id] * 2)
        self.core.outbound_connect.assert_not_awaited()
        await self.tick(RETRY_INTERVAL)
        self.assertEqual(self.quick_checked, [self.first.id] * FAILED_CHECKS + [self.second.id])
        self.assertEqual(self.connected_id(), self.second.id)
        # The failed server is quarantined; a failure does not count towards the limit.
        self.assertEqual(self.state.quarantine, {self.first.id: self.now + QUARANTINE})
        self.assertEqual(self.state.switches, [])

    async def test_a_passed_check_counts_failures_anew(self):
        for outcome in (False, False, True, False, False):
            self.quick[self.first.id] = outcome
            await self.tick(CHECK_INTERVAL)
        self.core.outbound_connect.assert_not_awaited()

    async def test_check_errors_count_as_failures(self):
        self.quick[self.first.id] = RuntimeError("no test endpoint")
        with self.assertLogs("server.handlers.auto_connect", level="ERROR"):
            for _ in range(FAILED_CHECKS):
                await self.tick(CHECK_INTERVAL)
        self.assertEqual(self.connected_id(), self.second.id)

    async def test_failed_server_stays_when_no_server_works(self):
        self.quick[self.first.id] = self.quick[self.second.id] = False
        for _ in range(FAILED_CHECKS):
            await self.tick(CHECK_INTERVAL)
        self.assertEqual(self.connected_id(), self.first.id)
        self.assertEqual(self.state.quarantine, {})
        # The next try is at the usual pace, not every RETRY_INTERVAL.
        self.forget_calls()
        await self.tick(RETRY_INTERVAL)
        self.assertEqual(self.quick_checked, [])
        self.quick[self.second.id] = True
        await self.tick(CHECK_INTERVAL - RETRY_INTERVAL)
        self.assertEqual(self.quick_checked, [self.first.id, self.second.id])
        self.assertEqual(self.connected_id(), self.second.id)

    async def test_server_filtered_by_ping_is_replaced(self):
        self.rate(self.first, 0, FilterReason.BY_PING)
        await self.run_finished()
        self.assertEqual(self.connected_id(), self.second.id)
        self.assertIn(self.first.id, self.state.quarantine)

    async def test_quarantine_grows_for_each_failure_within_a_day(self):
        durations = []
        for _ in range(5):
            auto_connect._strike(self.state, "x", self.now)
            durations.append(self.state.quarantine["x"] - self.now)
            self.now += 1
        minutes = [QUARANTINE, 2 * QUARANTINE, 4 * QUARANTINE, MAX_QUARANTINE, MAX_QUARANTINE]
        self.assertEqual(durations, minutes)
        # A day after the last failure, the first duration applies again.
        self.now += DAY
        auto_connect._strike(self.state, "x", self.now)
        self.assertEqual(self.state.quarantine["x"] - self.now, QUARANTINE)


class DegradationTests(AutoConnectTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.rate(self.first, 90)
        self.rate(self.second, 85)
        await self.enable()
        self.connected_at = self.now
        self.forget_calls()

    async def test_degraded_server_is_replaced(self):
        # Two quick checks in a row rated DEGRADED_DROP below the score.
        self.quick[self.first.id] = 90 - DEGRADED_DROP - 1
        await self.tick(CHECK_INTERVAL)
        self.quick[self.first.id] = 90 - DEGRADED_DROP
        await self.tick(CHECK_INTERVAL)
        self.quick[self.first.id] = 90 - DEGRADED_DROP - 1
        await self.tick(CHECK_INTERVAL)
        await self.tick(CHECK_INTERVAL)
        # Degraded, but connected less than MIN_STAY_DEGRADED ago.
        self.core.outbound_connect.assert_not_awaited()
        self.now = self.connected_at + MIN_STAY_DEGRADED
        await self.tick()
        self.assertEqual(self.connected_id(), self.second.id)
        self.assertIn(self.first.id, self.state.quarantine)
        self.assertEqual(self.state.switches, [self.now])

    async def test_replacement_must_be_margin_above_the_quick_rating(self):
        self.now = self.connected_at + MIN_STAY_DEGRADED
        quick = 90 - DEGRADED_DROP - 1
        self.quick[self.first.id] = quick
        self.rate(self.second, quick + MARGIN - 1)
        for _ in range(3):
            await self.tick(CHECK_INTERVAL)
        # Degraded twice, but no server was far enough ahead: counted anew.
        self.core.outbound_connect.assert_not_awaited()
        self.assertEqual(self.quick_checked, [self.first.id] * 3)
        self.rate(self.second, quick + MARGIN)
        await self.tick(CHECK_INTERVAL)
        self.assertEqual(self.connected_id(), self.second.id)


class ImprovementTests(AutoConnectTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.rate(self.first, 70)
        self.rate(self.second, 70)
        await self.enable()
        # Equal scores keep the stored order.
        self.assertEqual(self.connected_id(), self.first.id)
        self.now += MIN_STAY_IMPROVEMENT
        self.forget_calls()

    async def test_better_server_replaces_after_two_runs(self):
        self.rate(self.second, 70 + MARGIN)
        await self.run_finished()
        self.assertEqual(self.quick_checked, [])
        await self.run_finished()
        self.assertEqual(self.quick_checked, [self.second.id])
        self.assertEqual(self.connected_id(), self.second.id)
        self.assertEqual(self.state.switches, [self.now])
        # The server left for a better one is not quarantined.
        self.assertEqual(self.state.quarantine, {})

    async def test_server_less_than_margin_ahead_stays_out(self):
        self.rate(self.second, 70 + MARGIN - 1)
        for _ in range(5):
            await self.run_finished()
            self.now += MIN_STAY_IMPROVEMENT
        self.core.outbound_connect.assert_not_awaited()

    async def test_one_good_measurement_is_not_enough(self):
        # Scores are smoothed: 60, then 90 scores 75, less than 70 + MARGIN.
        for rating in (60, 90, 60, 95):
            self.rate(self.second, rating)
            await self.run_finished()
        self.core.outbound_connect.assert_not_awaited()
        # 67.5, then 95 scores 81.25 and 88.125: ahead two runs in a row.
        await self.run_finished()
        self.assertEqual(self.connected_id(), self.second.id)

    async def test_waits_after_the_last_switch(self):
        self.rate(self.second, 90)
        self.state.last_switch = self.now - MIN_STAY_IMPROVEMENT + 1
        await self.run_finished()
        await self.run_finished()
        self.core.outbound_connect.assert_not_awaited()
        self.now += 1
        await self.run_finished()
        self.assertEqual(self.connected_id(), self.second.id)

    async def test_switches_per_day_are_limited(self):
        self.rate(self.second, 90)
        # The limit is used up; the oldest switch leaves the day in a minute.
        self.state.switches = [self.now - DAY + 60] + [self.now - DAY / 2] * (DAILY_SWITCHES - 1)
        await self.run_finished()
        await self.run_finished()
        self.core.outbound_connect.assert_not_awaited()
        self.now += 60
        await self.run_finished()
        self.assertEqual(self.connected_id(), self.second.id)

    async def test_client_choice_wins_over_a_decision_in_progress(self):
        self.rate(self.second, 90)
        await self.run_finished()

        async def check(context, server, tests):
            await connect_outbound_server(self.context, self.first.id)
            return await self.quick_test(context, server, tests)

        with patch.object(auto_connect, "quick_test_outbound", check):
            await self.run_finished()
        self.assertEqual(self.connections(), [self.first.id])
        self.assertEqual(self.connected_id(), self.first.id)
        self.assertFalse(self.context.settings.server_settings.get().auto_connect)


class ServerListTests(AutoConnectTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        link = SubscriptionLink(url="https://example.com/sub")
        self.context.settings.subscription_link.save(link)

    def stored(self, name: str) -> OutboundServer:
        return next(server for server in self.store.get_all() if server.name == name)

    async def test_refresh_connects_the_best_server_when_the_connected_one_is_gone(self):
        self.rate(self.second, 70)
        self.store.set_connected(self.first.id)
        self.set_auto_connect(True)
        self.load.return_value = [vless("two"), vless("three")]
        await refresh_subscriptions(self.context)
        self.assertEqual(self.connections(), [self.second.id])
        self.assertEqual(self.connected_id(), self.second.id)

    async def test_removed_servers_are_forgotten(self):
        self.rate(self.first, 70)
        self.rate(self.second, 70 + MARGIN)
        await connect_outbound_server(self.context, self.first.id)
        self.set_auto_connect(True)
        await self.run_finished()
        self.assertEqual(self.state.better_runs, {self.second.id: 1})
        # The refresh replaces two with three; one keeps its id and the connection.
        self.load.return_value = [vless("one"), vless("three")]
        await refresh_subscriptions(self.context)
        self.assertEqual(self.connected_id(), self.first.id)
        self.assertEqual(self.state.better_runs, {})
        self.assertEqual(set(self.state.scores), {self.first.id})
        # The new server starts from scratch: two runs before it replaces one.
        third = self.stored("three")
        self.rate(third, 70 + MARGIN)
        await self.run_finished()
        self.assertEqual(self.connected_id(), self.first.id)
        self.now += MIN_STAY_IMPROVEMENT
        await self.run_finished()
        self.assertEqual(self.connected_id(), third.id)

    async def test_server_removed_or_filtered_during_its_check_is_skipped(self):
        third = vless("three")
        self.store.add_servers([third])
        for server, rating in ((self.first, 90), (self.second, 80), (third, 70)):
            self.rate(server, rating)

        async def check(context, server, tests):
            if server.id == self.first.id:
                self.store.delete(self.first.id)
            if server.id == self.second.id:
                self.context.settings.reg_filter.add(RegFilter(reg="two"))
            return await self.quick_test(context, server, tests)

        with patch.object(auto_connect, "quick_test_outbound", check):
            await self.enable()
        self.assertEqual(self.connections(), [third.id])
        self.assertEqual(self.state.quarantine, {})


class WatchTests(AutoConnectTestCase):
    async def test_watch_waits_while_the_mode_is_off_or_subscriptions_refresh(self):
        self.rate(self.first, 90)
        self.store.set_connected(self.first.id)
        await self.tick()
        self.assertEqual(self.quick_checked, [])
        self.set_auto_connect(True)
        with patch.object(self.context.tasks, "running", return_value=True):
            await self.tick()
        self.assertEqual(self.quick_checked, [])
        await self.tick()
        self.assertEqual(self.quick_checked, [self.first.id])

    async def test_quick_checks_use_the_outbound_tests_or_a_reachability_test(self):
        self.rate(self.first, 90)
        self.store.set_connected(self.first.id)
        self.set_auto_connect(True)
        checked_with = []

        async def check(context, server, tests):
            checked_with.append(tuple(tests))
            return await self.quick_test(context, server, tests)

        test = OutboundTest(
            url="https://example.com/", alias="site", rule=OutboundTestRule.ANY_STATUS
        )
        with patch.object(auto_connect, "quick_test_outbound", check):
            await self.tick()
            self.context.settings.server_settings.save(
                ServerSettings(outbound_tests=(test,), auto_connect=True)
            )
            await self.tick(CHECK_INTERVAL)
        self.assertEqual(checked_with, [(REACHABILITY_TEST,), (test,)])

    async def test_quick_check_fails_below_half_of_the_tests(self):
        tests = {"a": True, "b": False}
        self.assertTrue(auto_connect._passed(replace(self.first, tests=tests)))
        self.assertFalse(auto_connect._passed(replace(self.first, tests={**tests, "c": False})))
        by_ping = replace(self.first, tests={}, filtered=FilterReason.BY_PING)
        self.assertFalse(auto_connect._passed(by_ping))


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.core = AsyncMock(spec=CoreClient)
        self.enterContext(patch("server.main.MihomoClient", return_value=self.core))
        self.enterContext(
            patch("server.handlers.subscriptions.load_subscription", new_callable=AsyncMock)
        )
        self.enterContext(
            patch.object(
                auto_connect,
                "quick_test_outbound",
                AsyncMock(side_effect=lambda context, server, tests: replace(server, tests={})),
            )
        )
        self.remembered, self.best = vless("one"), vless("two")
        with SettingsStore() as settings:
            settings.server_settings.save(ServerSettings(auto_connect=True))
            settings.outbound_server.add_servers([self.remembered, self.best])
            for server, rating in ((self.remembered, 30), (self.best, 90)):
                settings.outbound_server.update_health(
                    server.id, ping=None, speed=None, rating=rating, tests={}, filtered=None
                )

    async def connected_at_startup(self) -> list[str]:
        async with application() as context:
            await startup_finished(context)
            return [call.args[0] for call in self.core.outbound_connect.await_args_list]

    async def test_startup_keeps_the_remembered_server(self):
        with SettingsStore() as settings:
            settings.outbound_server.set_connected(self.remembered.id)
        self.assertEqual(await self.connected_at_startup(), [self.remembered.id])

    async def test_startup_connects_the_best_server_if_none_is_remembered(self):
        self.assertEqual(await self.connected_at_startup(), [self.best.id])
