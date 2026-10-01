import asyncio
import sqlite3
import time
import unittest
from contextlib import chdir
from dataclasses import replace
from ipaddress import ip_network
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import AsyncMock, patch

from server.cores.core_client import CoreClient
from server.cores.mihomo.mihomo_client import MihomoClient, domain_regex, routing_rule_config
from server.main import application, configure_handlers
from server.models import (
    InboundServer,
    InboundType,
    RoutingAction,
    RoutingRule,
    RoutingRuleFieldError,
    pattern_matches,
    serialize,
)
from server.models.routing_rule import placed, without
from server.settings_store import SettingsStore
from server.tests.support import startup_finished
from server.tests.test_requests import Client

PROXY, DIRECT, BLOCK = RoutingAction.PROXY, RoutingAction.DIRECT, RoutingAction.BLOCK


def rule(priority: int, reg: str, action: RoutingAction = DIRECT, **values) -> RoutingRule:
    return RoutingRule(priority=priority, reg=reg, action=action, **values)


class PatternTests(unittest.TestCase):
    def test_wildcard_matches_any_characters_of_the_whole_text(self):
        cases = {
            ("*", ""): True,
            ("*", "anything at all"): True,
            ("youtube.com", "youtube.com"): True,
            ("youtube.com", "www.youtube.com"): False,
            ("*.youtube.com", "www.youtube.com"): True,
            ("*.youtube.com", "a.b.youtube.com"): True,
            ("*.youtube.com", "youtube.com"): False,
            ("*youtube.com", "notyoutube.com"): True,
            ("*RU*", "🇷🇺 RU Moscow"): True,
            ("RU*", "🇷🇺 RU Moscow"): False,
            ("a*b*c", "abc"): True,
            ("a*b*c", "aXbYc"): True,
            ("a*b*c", "acb"): False,
            ("*ab*b", "ab"): False,
            ("*ab*b", "abb"): True,
            ("a*a", "a"): False,
            ("a**b", "ab"): True,
        }
        for (pattern, text), expected in cases.items():
            with self.subTest(pattern=pattern, text=text):
                self.assertIs(pattern_matches(pattern, text), expected)

    def test_case_dots_and_other_characters(self):
        self.assertTrue(pattern_matches("YouTube.COM", "youtube.com"))
        self.assertTrue(pattern_matches("россия*", "Россия 2"))
        self.assertFalse(pattern_matches("a.c", "abc"))
        self.assertTrue(pattern_matches("(?i)^[a-]$", "(?I)^[A-]$"))

    def test_many_wildcards_do_not_backtrack(self):
        started = time.monotonic()
        self.assertFalse(pattern_matches("*a" * 30 + "*b", "a" * 200))
        self.assertLess(time.monotonic() - started, 0.5)


class RoutingRuleModelTests(unittest.TestCase):
    def test_patterns_are_normalized_and_classified(self):
        cases = {
            "YouTube.COM": ("youtube.com", None),
            "**.youtube.com": ("*.youtube.com", None),
            "*google*": ("*google*", None),
            "my_host-1.lan": ("my_host-1.lan", None),
            "*.*": ("*.*", None),
            "*": ("*", None),
            "**": ("*", None),
            "192.168.1.10": ("192.168.1.10", ip_network("192.168.1.10/32")),
            "192.168.1.*": ("192.168.1.*", ip_network("192.168.1.0/24")),
            "192.168.*": ("192.168.*", ip_network("192.168.0.0/16")),
            "10.*": ("10.*", ip_network("10.0.0.0/8")),
            "0.*": ("0.*", ip_network("0.0.0.0/8")),
            "2001:DB8:0::1": ("2001:db8::1", ip_network("2001:db8::1/128")),
            "::1": ("::1", ip_network("::1/128")),
        }
        for reg, (normalized, network) in cases.items():
            with self.subTest(reg=reg):
                routing_rule = rule(1, reg)
                self.assertEqual((routing_rule.reg, routing_rule.network), (normalized, network))

    def test_invalid_values_name_their_field(self):
        cases = {
            "": "Pattern must not be empty",
            "192.16*": "In an IP pattern * replaces whole octets at the end, e.g. 192.168.*",
            "192.*.1.1": "In an IP pattern * replaces whole octets at the end, e.g. 192.168.*",
            "*.1": "In an IP pattern * replaces whole octets at the end, e.g. 192.168.*",
            "256.*": "In an IP pattern * replaces whole octets at the end, e.g. 192.168.*",
            "192.168.01.*": "In an IP pattern * replaces whole octets at the end, e.g. 192.168.*",
            "1.2.3.4.*": "In an IP pattern * replaces whole octets at the end, e.g. 192.168.*",
            "1.2.3": "In an IP pattern * replaces whole octets at the end, e.g. 192.168.*",
            "2001:db8::*": "An IPv6 pattern must be an exact address",
            "fe80::1%eth0": "An IPv6 pattern must be an exact address",
            "ютуб.рф": "A domain pattern may contain only Latin letters, digits, -, _, . and *",
            "you tube.com": "A domain pattern may contain only Latin letters, digits, -, _, . and *",
            "^youtube$": "A domain pattern may contain only Latin letters, digits, -, _, . and *",
            "a?b": "A domain pattern may contain only Latin letters, digits, -, _, . and *",
        }
        for reg, message in cases.items():
            with self.subTest(reg=reg), self.assertRaises(RoutingRuleFieldError) as raised:
                rule(1, reg)
            self.assertEqual((str(raised.exception), raised.exception.field), (message, "reg"))
        invalid: list[tuple[dict[str, Any], str]] = [
            ({"priority": 0}, "priority"),
            ({"priority": True}, "priority"),
            ({"action": "direct"}, "action"),
            ({"id": ""}, "id"),
        ]
        for values, name in invalid:
            fields: dict[str, Any] = {"priority": 1, "reg": "a.com", "action": DIRECT, **values}
            with self.subTest(name), self.assertRaises(RoutingRuleFieldError) as raised:
                RoutingRule(**fields)
            self.assertEqual(raised.exception.field, name)

    def test_serialization(self):
        routing_rule = rule(2, "*.Example.com", BLOCK, id="r")
        self.assertEqual(
            serialize(routing_rule),
            {"id": "r", "priority": 2, "reg": "*.example.com", "action": "block"},
        )

    def test_placed_and_without_renumber_the_others(self):
        a, b, c = rule(1, "a.com"), rule(2, "b.com"), rule(3, "c.com")
        new = rule(2, "new.com")
        self.assertEqual(
            placed([c, a, b], new),
            [a, new, replace(b, priority=3), replace(c, priority=4)],
        )
        self.assertEqual(placed([a, b, c], rule(4, "d.com"))[-1].priority, 4)
        # A stored rule moves: the ones between its places shift toward its old place.
        self.assertEqual(
            placed([a, b, c], replace(c, priority=1)),
            [replace(c, priority=1), replace(a, priority=2), replace(b, priority=3)],
        )
        self.assertEqual(
            placed([a, b, c], replace(a, priority=3)),
            [replace(b, priority=1), replace(c, priority=2), replace(a, priority=3)],
        )
        self.assertEqual(
            placed([a, b, c], replace(b, action=BLOCK)), [a, replace(b, action=BLOCK), c]
        )
        with self.assertRaises(RoutingRuleFieldError) as raised:
            placed([a, b, c], rule(5, "e.com"))
        self.assertEqual(
            (str(raised.exception), raised.exception.field),
            ("Priority must be between 1 and 4", "priority"),
        )
        with self.assertRaises(RoutingRuleFieldError):
            placed([a, b, c], replace(a, priority=4))
        self.assertEqual(without([a, b, c], a.id), [replace(b, priority=1), replace(c, priority=2)])
        self.assertEqual(without([a, b, c], "missing"), [a, b, c])


class RoutingRuleStoreTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(chdir(self.enterContext(TemporaryDirectory())))

    def test_rules_keep_their_priorities_numbered(self):
        with SettingsStore() as settings:
            store = settings.routing_rule
            self.assertEqual(store.get_all(), [])
            a, b = rule(1, "a.com"), rule(2, "192.168.*", BLOCK)
            store.save(a)
            store.save(b)
            first = rule(1, "first.com", PROXY)
            store.save(first)
            self.assertEqual(
                store.get_all(), [first, replace(a, priority=2), replace(b, priority=3)]
            )
            store.save(replace(first, priority=3, reg="moved.com"))
            moved = replace(first, priority=3, reg="moved.com")
            self.assertEqual(store.get_all(), [a, replace(b, priority=2), moved])
            self.assertEqual(store.get_by_id(moved.id), moved)
            self.assertIsNone(store.get_by_id("missing"))
            with self.assertRaises(sqlite3.IntegrityError):
                store.save(rule(1, "A.com"))
            with self.assertRaises(RoutingRuleFieldError):
                store.save(rule(5, "e.com"))
            self.assertEqual(store.get_all(), [a, replace(b, priority=2), moved])
            self.assertTrue(store.delete(a.id))
            self.assertFalse(store.delete(a.id))
        with SettingsStore() as settings:
            self.assertEqual(
                settings.routing_rule.get_all(),
                [replace(b, priority=1), replace(moved, priority=2)],
            )


class RoutingRuleRequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(chdir(self.enterContext(TemporaryDirectory())))
        with SettingsStore() as settings:
            self.stored_rule = rule(1, "stored.com")
            settings.routing_rule.save(self.stored_rule)
        self.core = AsyncMock(spec=CoreClient)
        self.core.test_port = 20809
        self.calls: list[str] = []
        self.core.routing_set.side_effect = lambda rules: self.calls.append("routing_set")
        self.core.inbound_set.side_effect = lambda inbound: self.calls.append("inbound_set")
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
        self.snapshot = next(
            frame for frame in self.client.frames if frame["model"] == "routing_rule"
        )
        await startup_finished(self.context)
        self.client.frames.clear()
        self.core.reset_mock()

    def stored(self) -> list[RoutingRule]:
        return self.context.settings.routing_rule.get_all()

    async def seed(self, *rules: RoutingRule) -> None:
        """Store rules after the stored one; their message reaches the client and is dropped."""
        for routing_rule in rules:
            self.context.settings.routing_rule.save(routing_rule)
        await self.context.sync.notify("routing_rule")
        async with asyncio.timeout(2):
            while not self.client.frames:
                self.client.received.clear()
                await self.client.received.wait()
        self.client.frames.clear()

    async def test_startup_applies_stored_rules_before_the_inbounds(self):
        self.assertEqual(self.calls[:2], ["routing_set", "inbound_set"])
        self.assertEqual(self.snapshot["payload"], [serialize(self.stored_rule)])

    async def test_add_puts_the_rule_at_its_priority(self):
        updates, response = await self.client.request(
            "add", "routing_rule", {"reg": "*.YouTube.com", "action": "proxy"}
        )
        self.assertTrue(response["ok"], response)
        last_id = response["payload"]["id"]
        last = RoutingRule(id=last_id, priority=2, reg="*.youtube.com", action=PROXY)
        self.assertEqual(self.stored(), [self.stored_rule, last])
        self.core.routing_set.assert_awaited_once_with([self.stored_rule, last])
        self.assertEqual(
            [(update["model"], update["payload"], update["deleted_ids"]) for update in updates],
            [("routing_rule", [serialize(last)], [])],
        )
        self.core.reset_mock()
        updates, response = await self.client.request(
            "add", "routing_rule", {"reg": "192.168.*", "action": "block", "priority": 1}
        )
        self.assertTrue(response["ok"], response)
        first = RoutingRule(id=response["payload"]["id"], priority=1, reg="192.168.*", action=BLOCK)
        expected = [first, replace(self.stored_rule, priority=2), replace(last, priority=3)]
        self.assertEqual(self.stored(), expected)
        self.core.routing_set.assert_awaited_once_with(expected)
        # The new rule and the ones it moved down arrive in one message.
        [update] = updates
        self.assertEqual(update["payload"], [serialize(item) for item in expected])

    async def test_change_moves_and_edits_the_rule(self):
        second = rule(2, "second.com")
        third = rule(3, "third.com")
        await self.seed(second, third)
        updates, response = await self.client.request(
            "change", "routing_rule", {"id": third.id, "priority": 1, "action": "block"}
        )
        self.assertEqual((response["ok"], response["payload"]), (True, {}))
        expected = [
            replace(third, priority=1, action=BLOCK),
            replace(self.stored_rule, priority=2),
            replace(second, priority=3),
        ]
        self.assertEqual(self.stored(), expected)
        self.core.routing_set.assert_awaited_once_with(expected)
        self.assertEqual(updates[0]["payload"], [serialize(item) for item in expected])
        self.core.reset_mock()
        updates, response = await self.client.request(
            "change", "routing_rule", {"id": second.id, "reg": "*.Second.com"}
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(self.stored()[2], replace(second, priority=3, reg="*.second.com"))
        self.assertEqual(len(updates[0]["payload"]), 1)
        # The same values change nothing and do not touch the core.
        self.core.reset_mock()
        updates, response = await self.client.request(
            "change", "routing_rule", {"id": second.id, "priority": 3, "reg": "*.second.com"}
        )
        self.assertTrue(response["ok"], response)
        self.assertEqual(updates, [])
        self.core.routing_set.assert_not_awaited()

    async def test_delete_moves_the_rest_up(self):
        second = rule(2, "second.com")
        await self.seed(second)
        updates, response = await self.client.request(
            "delete", "routing_rule", {"id": self.stored_rule.id}
        )
        self.assertEqual((response["ok"], response["payload"]), (True, {}))
        self.assertEqual(self.stored(), [replace(second, priority=1)])
        self.core.routing_set.assert_awaited_once_with([replace(second, priority=1)])
        self.assertEqual(
            [(update["payload"], update["deleted_ids"]) for update in updates],
            [([serialize(replace(second, priority=1))], [self.stored_rule.id])],
        )

    async def test_errors_change_nothing(self):
        stored_id = self.stored_rule.id
        cases = [
            ("add", {"action": "direct"}, "bad_request", {"field": "reg"}),
            ("add", {"reg": "a.com"}, "bad_request", {"field": "action"}),
            (
                "add",
                {"reg": "a.com", "action": "direct", "id": "x"},
                "bad_request",
                {"field": "id"},
            ),
            ("add", {"reg": 1, "action": "direct"}, "bad_request", {"field": "reg"}),
            (
                "add",
                {"reg": "a.com", "action": "direct", "priority": "1"},
                "bad_request",
                {"field": "priority"},
            ),
            (
                "add",
                {"reg": "a.com", "action": "direct", "priority": True},
                "bad_request",
                {"field": "priority"},
            ),
            ("add", {"reg": "a.com", "action": "reject"}, "validation_error", {"field": "action"}),
            ("add", {"reg": "", "action": "direct"}, "validation_error", {"field": "reg"}),
            ("add", {"reg": "192.16*", "action": "direct"}, "validation_error", {"field": "reg"}),
            (
                "add",
                {"reg": "a.com", "action": "direct", "priority": 0},
                "validation_error",
                {"field": "priority"},
            ),
            (
                "add",
                {"reg": "a.com", "action": "direct", "priority": 3},
                "validation_error",
                {"field": "priority"},
            ),
            ("add", {"reg": "STORED.com", "action": "block"}, "conflict", {"field": "reg"}),
            ("change", {"reg": "a.com"}, "bad_request", {"field": "id"}),
            ("change", {"id": "missing", "reg": "a.com"}, "not_found", {"field": "id"}),
            ("change", {"id": stored_id, "priority": 2}, "validation_error", {"field": "priority"}),
            ("change", {"id": stored_id, "reg": "a b"}, "validation_error", {"field": "reg"}),
            ("change", {"id": stored_id, "unknown": 1}, "bad_request", {"field": "unknown"}),
            ("delete", {"id": "missing"}, "not_found", {"field": "id"}),
            ("delete", {}, "bad_request", {"field": "id"}),
        ]
        for request_type, payload, code, details in cases:
            with self.subTest(request_type=request_type, payload=payload):
                error = await self.client.error(request_type, "routing_rule", payload)
                self.assertEqual((error["code"], error["details"]), (code, details))
        error = await self.client.error(
            "add", "routing_rule", {"reg": "192.16*", "action": "direct"}
        )
        self.assertEqual(
            error["message"], "In an IP pattern * replaces whole octets at the end, e.g. 192.168.*"
        )
        self.assertEqual(self.stored(), [self.stored_rule])
        self.core.routing_set.assert_not_awaited()
        self.assertEqual(self.client.frames, [])

    async def test_core_failures_save_nothing(self):
        self.core.routing_set.side_effect = RuntimeError("core is down")
        for request_type, payload in (
            ("add", {"reg": "a.com", "action": "direct"}),
            ("change", {"id": self.stored_rule.id, "action": "block"}),
            ("delete", {"id": self.stored_rule.id}),
        ):
            with self.subTest(request_type), self.assertLogs("server.handlers.routing_rule"):
                error = await self.client.error(request_type, "routing_rule", payload)
            self.assertEqual(error["code"], "core_error")
        self.assertEqual(self.stored(), [self.stored_rule])
        self.assertEqual(self.client.frames, [])


class MihomoRoutingConfigTests(unittest.TestCase):
    def test_domain_regex(self):
        self.assertEqual(domain_regex("youtube.com"), r"^youtube\.com$")
        self.assertEqual(domain_regex("*.youtube.com"), r"^.*\.youtube\.com$")
        self.assertEqual(domain_regex("*google*"), r"^(?>.*?google).*$")
        self.assertEqual(domain_regex("a*b-c*d_e"), r"^a(?>.*?b-c).*d_e$")

    def test_rules(self):
        cases = [
            (rule(1, "*.youtube.com", PROXY), r"DOMAIN-REGEX,^.*\.youtube\.com$,main"),
            (rule(1, "youtube.com", BLOCK), r"DOMAIN-REGEX,^youtube\.com$,REJECT"),
            (rule(1, "192.168.*", DIRECT), "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve"),
            (rule(1, "10.0.0.1", DIRECT), "IP-CIDR,10.0.0.1/32,DIRECT,no-resolve"),
            (rule(1, "::1", BLOCK), "IP-CIDR6,::1/128,REJECT,no-resolve"),
            (rule(1, "*", DIRECT), "MATCH,DIRECT"),
        ]
        for routing_rule, expected in cases:
            with self.subTest(reg=routing_rule.reg):
                self.assertEqual(routing_rule_config(routing_rule), expected)

    def test_routing_rules_go_after_the_test_endpoint_and_before_the_inbounds(self):
        client = MihomoClient()
        client.test_port = 20809
        listener = InboundServer(type=InboundType.PROXY, proxy_port=1080, id="in")
        config = client._build_config(
            [],
            {"in": listener},
            [rule(1, "a.com", BLOCK), rule(2, "*", DIRECT)],
            {"main": "REJECT", "test": "REJECT"},
        )
        self.assertEqual(
            config["rules"],
            [
                "IN-NAME,test,test",
                r"DOMAIN-REGEX,^a\.com$,REJECT",
                "MATCH,DIRECT",
                "IN-NAME,in,main",
                "MATCH,REJECT",
            ],
        )
