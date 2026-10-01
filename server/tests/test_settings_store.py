import json
import sqlite3
import unittest
from contextlib import chdir
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from server.models.outbound_server import (
    FilterReason,
    GrpcMode,
    OutboundProtocol,
    OutboundSecurity,
    OutboundServer,
    OutboundTransport,
    ShadowsocksMethod,
    UotVersion,
    VlessFlow,
    XhttpMode,
)
from server.models.outbound_test import OutboundTest, OutboundTestRule
from server.models.reg_filter import RegFilter
from server.models.server_settings import ServerSettings
from server.models.subscription_link import SubscriptionLink
from server.settings_store import SettingsStore


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.db_path = Path(directory) / "settings.sqlite3"
        self.assertFalse(self.db_path.exists())
        self.store = self.enterContext(SettingsStore())
        self.assertTrue(self.db_path.is_file())

    def test_create_update_delete_and_restore(self):
        self.assertEqual(self.store.subscription_link.get_all(), [])
        self.assertIsNone(self.store.subscription_link.get_by_id("missing"))
        first = SubscriptionLink(url="https://example.com/one")
        second = SubscriptionLink(url="https://example.com/two")
        self.store.subscription_link.save(first)
        self.store.subscription_link.save(second)
        updated = replace(first, url="https://example.com/updated")
        self.store.subscription_link.save(updated)
        self.assertEqual(self.store.subscription_link.get_by_id(first.id), updated)
        self.assertEqual(self.store.subscription_link.get_all(), [updated, second])

        # A separate connection sees committed writes before the store is closed.
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT id, url FROM subscription_links ORDER BY rowid"
            ).fetchall()
        self.assertEqual(rows, [(updated.id, updated.url), (second.id, second.url)])

        self.assertTrue(self.store.subscription_link.delete(second.id))
        self.assertFalse(self.store.subscription_link.delete(second.id))
        self.assertIsNone(self.store.subscription_link.get_by_id(second.id))
        self.store.close()
        with SettingsStore() as restored:
            self.assertEqual(restored.subscription_link.get_all(), [updated])
            self.assertEqual(restored.subscription_link.get_by_id(first.id), updated)

    def test_reg_filters_are_unique_and_kept_in_order(self):
        filters = self.store.reg_filter
        self.assertEqual(filters.get_all(), [])
        first, second = RegFilter(reg="RU*"), RegFilter(reg="*test*")
        filters.add(first)
        filters.add(second)
        self.assertEqual(filters.get_all(), [first, second])
        # The same pattern under another id is rejected.
        with self.assertRaises(sqlite3.IntegrityError):
            filters.add(RegFilter(reg="RU*"))
        self.assertTrue(filters.delete(first.id))
        self.assertFalse(filters.delete(first.id))
        self.store.close()
        with SettingsStore() as restored:
            self.assertEqual(restored.reg_filter.get_all(), [second])

    def test_url_short_is_derived_on_every_construction(self):
        cases = {
            "https://user:token@Sub.Example.com:8443/path/token?key=value#frag": (
                "https://sub.example.com"
            ),
            "http://203.0.113.5:8080/sub": "http://203.0.113.5",
            "https://[2001:db8::1]:443/sub": "https://[2001:db8::1]",
        }
        for url, short in cases.items():
            with self.subTest(url=url):
                self.assertEqual(SubscriptionLink(url=url).url_short, short)
        link = SubscriptionLink(url="https://one.example.com/token")
        self.store.subscription_link.save(link)
        [loaded] = self.store.subscription_link.get_all()
        self.assertEqual(loaded.url_short, "https://one.example.com")
        stored = self.store.subscription_link.get_by_id(link.id)
        assert stored is not None
        self.assertEqual(stored.url_short, "https://one.example.com")
        moved = replace(link, url="https://two.example.com/token")
        self.assertEqual(moved.url_short, "https://two.example.com")
        with self.assertRaises(TypeError):
            SubscriptionLink(url=link.url, url_short="x")  # ty: ignore[unknown-argument]
        self.assertNotIn("token", repr(link))

    def test_read_returns_snapshot(self):
        link = SubscriptionLink(url="https://example.com/sub")
        self.store.subscription_link.save(link)
        self.store.subscription_link.get_all().clear()
        self.assertEqual(self.store.subscription_link.get_all(), [link])

    def test_getters_read_changes_from_another_connection(self):
        link = SubscriptionLink(url="https://example.com/sub")
        self.assertEqual(self.store.subscription_link.get_all(), [])
        self.assertIsNone(self.store.subscription_link.get_by_id(link.id))
        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        with connection:
            connection.execute(
                "INSERT INTO subscription_links (id, url) VALUES (?, ?)", (link.id, link.url)
            )
        self.assertEqual(self.store.subscription_link.get_all(), [link])
        self.assertEqual(self.store.subscription_link.get_by_id(link.id), link)

        updated = replace(link, url="https://example.com/updated")
        with connection:
            connection.execute(
                "UPDATE subscription_links SET url = ? WHERE id = ?", (updated.url, updated.id)
            )
        self.assertEqual(self.store.subscription_link.get_all(), [updated])
        self.assertEqual(self.store.subscription_link.get_by_id(link.id), updated)

        with connection:
            connection.execute("DELETE FROM subscription_links WHERE id = ?", (link.id,))
        self.assertEqual(self.store.subscription_link.get_all(), [])
        self.assertIsNone(self.store.subscription_link.get_by_id(link.id))

    def test_duplicate_url_does_not_change_database(self):
        first = SubscriptionLink(url="https://example.com/one")
        second = SubscriptionLink(url="https://example.com/two")
        self.store.subscription_link.save(first)
        self.store.subscription_link.save(second)
        for duplicate in (SubscriptionLink(url=first.url), replace(second, url=first.url)):
            with self.subTest(id=duplicate.id), self.assertRaises(sqlite3.IntegrityError):
                self.store.subscription_link.save(duplicate)
            self.assertEqual(self.store.subscription_link.get_all(), [first, second])
        self.store.close()
        with SettingsStore() as restored:
            self.assertEqual(restored.subscription_link.get_all(), [first, second])

    def test_failed_writes_leave_database_unchanged(self):
        link = SubscriptionLink(url="https://example.com/sub")
        self.store.subscription_link.save(link)
        # Force genuine SQLite failures for both insert/update and delete operations.
        self.store._connection.execute("PRAGMA query_only = ON")
        with self.assertRaises(sqlite3.OperationalError):
            self.store.subscription_link.save(replace(link, url="https://example.com/new"))
        with self.assertRaises(sqlite3.OperationalError):
            self.store.subscription_link.delete(link.id)
        self.assertEqual(self.store.subscription_link.get_all(), [link])
        self.store._connection.execute("PRAGMA query_only = OFF")
        self.assertTrue(self.store.subscription_link.delete(link.id))
        self.store.close()
        with SettingsStore() as restored:
            self.assertEqual(restored.subscription_link.get_all(), [])

    def test_repeated_construction_shares_store_and_entity(self):
        another = SettingsStore()
        self.assertIs(another, self.store)
        self.assertIs(another.subscription_link, self.store.subscription_link)
        self.assertIs(another.outbound_server, self.store.outbound_server)
        link = SubscriptionLink(url="https://example.com/sub")
        another.subscription_link.save(link)
        self.assertEqual(self.store.subscription_link.get_by_id(link.id), link)

    def test_close_allows_reopening_without_old_close_affecting_new_store(self):
        self.store.close()
        with SettingsStore() as reopened:
            self.assertIsNot(reopened, self.store)
            self.store.close()
            self.assertIs(SettingsStore(), reopened)
            self.assertEqual(reopened.subscription_link.get_all(), [])


class ServerSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.store = self.enterContext(SettingsStore())

    def rows(self) -> list[tuple]:
        with sqlite3.connect("settings.sqlite3") as connection:
            return connection.execute("SELECT * FROM server_settings").fetchall()

    def test_defaults_are_stored_as_the_only_row(self):
        settings = self.store.server_settings.get()
        self.assertEqual(settings, ServerSettings())
        self.assertEqual(settings.id, 0)
        self.assertEqual(settings.subscription_refresh_interval, 86400)
        self.assertIsNone(settings.last_subscription_refresh)
        self.assertIs(settings.auto_connect, False)
        self.assertEqual(self.rows(), [(0, 86400, None, 0)])

    def test_save_replaces_the_row_and_persists_utc(self):
        moscow = timezone(timedelta(hours=3))
        changed = ServerSettings(
            subscription_refresh_interval=3600,
            last_subscription_refresh=datetime(2026, 9, 26, 15, 30, tzinfo=moscow),
        )
        self.store.server_settings.save(changed)
        changed = replace(changed, subscription_refresh_interval=600, auto_connect=True)
        self.store.server_settings.save(changed)
        self.assertEqual(self.rows(), [(0, 600, "2026-09-26T12:30:00+00:00", 1)])
        self.store.close()
        with SettingsStore() as reopened:
            loaded = reopened.server_settings.get()
        self.assertEqual(loaded, changed)
        self.assertIs(loaded.auto_connect, True)
        assert loaded.last_subscription_refresh is not None
        self.assertIs(loaded.last_subscription_refresh.tzinfo, UTC)

    def test_outbound_tests_are_added_and_deleted(self):
        tests = self.store.outbound_test
        self.assertEqual(tests.get_all(), [])
        google = OutboundTest(
            url="https://www.gstatic.com/generate_204", rule=OutboundTestRule.STATUS_204
        )
        site = OutboundTest(url="https://сайт.рф/", rule=OutboundTestRule.STATUS_BELOW_503)
        tests.add(google)
        tests.add(site)
        with self.assertRaises(sqlite3.IntegrityError):
            tests.add(replace(google, id="other", rule=OutboundTestRule.ANY_STATUS))
        self.store.close()
        with SettingsStore() as reopened:
            self.assertEqual(reopened.outbound_test.get_all(), [google, site])
            self.assertTrue(reopened.outbound_test.delete(google.id))
            self.assertFalse(reopened.outbound_test.delete(google.id))
            self.assertEqual(reopened.outbound_test.get_all(), [site])

    def test_tests_of_older_databases_move_to_their_table(self):
        server = OutboundServer(
            name="NL",
            address="example.com",
            port=443,
            protocol=OutboundProtocol.VLESS,
            vless_uuid=UUID(int=1),
            tests={"google": True, "site": False, "gone": True},
        )
        self.store.outbound_server.save(server)
        self.store.close()
        old_tests = [
            {
                "url": "https://www.gstatic.com/generate_204",
                "alias": "google",
                "rule": "status_204",
            },
            {"url": "https://example.com/", "alias": "site", "rule": "status_below_503"},
        ]
        with sqlite3.connect("settings.sqlite3") as connection:
            connection.execute("DROP TABLE server_settings")
            connection.execute(
                "CREATE TABLE server_settings ("
                "id INTEGER PRIMARY KEY NOT NULL CHECK (id = 0), "
                "subscription_refresh_interval INTEGER NOT NULL, "
                "last_subscription_refresh TEXT, "
                "outbound_tests TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO server_settings VALUES (0, 600, NULL, ?)", (json.dumps(old_tests),)
            )
        connection.close()
        with SettingsStore() as reopened:
            google, site = reopened.outbound_test.get_all()
            self.assertEqual(
                [(test.url, test.rule) for test in (google, site)],
                [
                    ("https://www.gstatic.com/generate_204", OutboundTestRule.STATUS_204),
                    ("https://example.com/", OutboundTestRule.STATUS_BELOW_503),
                ],
            )
            stored = reopened.outbound_server.get_by_id(server.id)
            assert stored is not None
            self.assertEqual(stored.tests, {google.id: True, site.id: False})
            self.assertEqual(
                reopened.server_settings.get(), ServerSettings(subscription_refresh_interval=600)
            )
        self.assertEqual(self.rows(), [(0, 600, None, 0)])
        # Moved once: reopening keeps the ids.
        with SettingsStore() as reopened:
            self.assertEqual(reopened.outbound_test.get_all(), [google, site])

    def test_auto_connect_column_is_added_to_older_databases(self):
        self.store.close()
        with sqlite3.connect("settings.sqlite3") as connection:
            connection.execute("DROP TABLE server_settings")
            connection.execute(
                "CREATE TABLE server_settings ("
                "id INTEGER PRIMARY KEY NOT NULL CHECK (id = 0), "
                "subscription_refresh_interval INTEGER NOT NULL, "
                "last_subscription_refresh TEXT, "
                "outbound_tests TEXT NOT NULL)"
            )
            connection.execute("INSERT INTO server_settings VALUES (0, 600, NULL, '[]')")
        connection.close()
        with SettingsStore() as reopened:
            settings = reopened.server_settings.get()
            self.assertEqual(settings, ServerSettings(subscription_refresh_interval=600))
            reopened.server_settings.save(replace(settings, auto_connect=True))
            self.assertIs(reopened.server_settings.get().auto_connect, True)

    def test_database_rejects_a_second_row(self):
        connection = sqlite3.connect("settings.sqlite3")
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.IntegrityError), connection:
            connection.execute(
                "INSERT INTO server_settings (id, subscription_refresh_interval) VALUES (1, 60)"
            )
        self.assertEqual(len(self.rows()), 1)

    def test_invalid_values(self):
        with self.assertRaises(TypeError):
            ServerSettings(id=1)  # ty: ignore[unknown-argument]
        for interval in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                ServerSettings(subscription_refresh_interval=interval)  # ty: ignore[invalid-argument-type]
        for auto_connect in (1, "true", None):
            with self.assertRaises(ValueError):
                ServerSettings(auto_connect=auto_connect)  # ty: ignore[invalid-argument-type]
        with self.assertRaises(ValueError):
            ServerSettings(last_subscription_refresh=datetime(2026, 9, 26))  # noqa: DTZ001 - naive on purpose
        test = OutboundTest(url="https://example.com", rule=OutboundTestRule.ANY_STATUS)
        for changes in ({"url": "ftp://example.com"}, {"url": "https://"}, {"id": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(test, **changes)

    def test_rules(self):
        cases = {
            OutboundTestRule.STATUS_204: ({204}, {200, 404}),
            OutboundTestRule.STATUS_2XX: ({200, 204, 299}, {199, 301, 500}),
            OutboundTestRule.STATUS_BELOW_400: ({200, 302, 399}, {400, 503}),
            OutboundTestRule.STATUS_BELOW_500: ({200, 404, 499}, {500, 503}),
            OutboundTestRule.STATUS_BELOW_503: ({200, 404, 502}, {503, 504}),
            OutboundTestRule.ANY_STATUS: ({100, 200, 404, 503, 599}, set()),
        }
        self.assertEqual(cases.keys(), set(OutboundTestRule))
        for rule, (accepted, rejected) in cases.items():
            for status in accepted:
                self.assertTrue(rule.accepts(status), (rule, status))
            for status in rejected:
                self.assertFalse(rule.accepts(status), (rule, status))


class OutboundSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.store = self.enterContext(SettingsStore())
        self.servers = self.store.outbound_server

    def server(self, **changes) -> OutboundServer:
        return replace(
            OutboundServer(
                name="Profile",
                address="example.com",
                port=443,
                subscription_id="subscription",
                protocol=OutboundProtocol.VLESS,
                vless_uuid=UUID(int=1),
            ),
            **changes,
        )

    def other_protocol(self, **changes) -> OutboundServer:
        return OutboundServer(
            name="Profile",
            address="example.com",
            port=443,
            subscription_id="subscription",
            **changes,
        )

    def test_round_trip_all_protocols_and_nested_settings(self):
        profiles = [
            self.server(
                vless_uuid=UUID(int=2),
                vless_flow=VlessFlow.VISION,
                vless_extra={"nested": [None, True, 3, {"x": "y"}]},
                transport=OutboundTransport.XHTTP,
                security=OutboundSecurity.REALITY,
                xhttp_mode=XhttpMode.STREAM_ONE,
                grpc_mode=GrpcMode.MULTI,
                alpn=("h2", "http/1.1"),
                server_name="sni.example.com",
                fingerprint="chrome",
                public_key="key",
                short_id="abcd",
                spider_x="/",
                allow_insecure=False,
                host="host.example.com",
                path="/path",
                service_name="service",
                stream_options={"sockopt": {"tcpFastOpen": True}},
                extra_params={"custom": "value"},
                source_tag="remote",
            ),
            self.other_protocol(
                protocol=OutboundProtocol.SHADOWSOCKS,
                shadowsocks_password="password",
                shadowsocks_method=ShadowsocksMethod.AES_128_GCM,
                shadowsocks_udp_over_tcp=True,
                shadowsocks_uot_version=UotVersion.V2,
                shadowsocks_extra={"custom": 1},
            ),
            self.other_protocol(
                protocol=OutboundProtocol.HYSTERIA,
                hysteria_auth="auth",
                hysteria_extra={"custom": "value"},
            ),
        ]
        self.servers.add_servers(profiles)
        self.store.close()
        with SettingsStore() as reopened:
            loaded = reopened.outbound_server.get_all()
            self.assertEqual(loaded, profiles)
            for actual, expected in zip(loaded, profiles, strict=True):
                self.assertIsInstance(actual.protocol, OutboundProtocol)
                self.assertIsInstance(actual.transport, OutboundTransport)
                self.assertIsInstance(actual.security, OutboundSecurity)
                self.assertIsInstance(actual.alpn, tuple)
            vless, shadowsocks, hysteria = loaded
            self.assertIsInstance(vless.vless_uuid, UUID)
            self.assertIs(vless.vless_flow, VlessFlow.VISION)
            self.assertIs(vless.grpc_mode, GrpcMode.MULTI)
            self.assertIs(vless.xhttp_mode, XhttpMode.STREAM_ONE)
            self.assertIsNone(vless.shadowsocks_method)
            self.assertIs(shadowsocks.shadowsocks_method, ShadowsocksMethod.AES_128_GCM)
            self.assertIs(shadowsocks.shadowsocks_uot_version, UotVersion.V2)
            self.assertIs(shadowsocks.shadowsocks_udp_over_tcp, True)
            self.assertIsNone(shadowsocks.vless_uuid)
            self.assertEqual(hysteria.hysteria_version, 2)

    def test_health_round_trip_and_json_tests_column(self):
        server = self.server(
            ping=120, speed=2_500_000, rating=7, tests={"google": True, "сайт": False}
        )
        self.servers.save(server)
        connection = sqlite3.connect("settings.sqlite3")
        self.addCleanup(connection.close)
        row = connection.execute(
            "SELECT ping, speed, rating, tests FROM outbound_servers"
        ).fetchone()
        self.assertEqual(row[:3], (120, 2_500_000, 7))
        self.assertEqual(json.loads(row[3]), {"google": True, "сайт": False})
        self.assertEqual(self.servers.get_by_id(server.id), server)
        unchecked = self.server(name="unchecked")
        self.servers.save(unchecked)
        self.assertEqual(
            connection.execute(
                "SELECT ping, speed, rating, tests FROM outbound_servers WHERE id = ?",
                (unchecked.id,),
            ).fetchone(),
            (None, None, None, None),
        )
        for changes in ({"ping": -1}, {"speed": 1.5}, {"rating": True}, {"tests": {"a": 1}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.server(**changes)

    def test_connected_server_is_unique_and_survives_refresh(self):
        first, second = self.server(name="one"), self.server(name="two")
        self.servers.add_servers([first, second])
        self.assertIsNone(self.servers.get_connected())
        connected = self.servers.set_connected(first.id)
        self.assertEqual(connected, replace(first, is_connected=True))
        self.assertEqual(self.servers.set_connected(second.id), replace(second, is_connected=True))
        self.assertEqual([server.is_connected for server in self.servers.get_all()], [False, True])
        # The database itself keeps at most one connected server.
        with self.assertRaises(sqlite3.IntegrityError):
            self.servers.save(replace(first, is_connected=True))
        # A refresh keeps the flag of the matched profile; health updates keep it too.
        self.servers.update_servers([self.server(name="two", path="/new"), self.server(name="one")])
        self.servers.update_health(second.id, ping=1, speed=1, rating=1, tests={}, filtered=None)
        connected = self.servers.get_connected()
        assert connected is not None
        self.assertEqual((connected.id, connected.path), (second.id, "/new"))
        self.assertIsNone(self.servers.set_connected("missing"))
        self.assertIsNone(self.servers.get_connected())
        self.servers.set_connected(first.id)
        self.assertIsNone(self.servers.set_connected(None))
        self.assertIsNone(self.servers.get_connected())
        # The flag goes away with its server.
        self.servers.set_connected(first.id)
        self.servers.update_servers([self.server(name="two")])
        self.assertIsNone(self.servers.get_connected())

    def test_update_health_changes_only_check_results(self):
        server = self.server()
        self.servers.save(server)
        self.servers.save(replace(server, path="/newer"))
        updated = self.servers.update_health(
            server.id, ping=10, speed=20, rating=30, tests={"a": True}, filtered=None
        )
        self.assertEqual(
            updated, replace(server, path="/newer", ping=10, speed=20, rating=30, tests={"a": True})
        )
        self.assertEqual(self.servers.get_by_id(server.id), updated)
        cleared = self.servers.update_health(
            server.id, ping=None, speed=None, rating=0, tests={}, filtered=None
        )
        assert cleared is not None
        self.assertEqual((cleared.ping, cleared.rating, cleared.tests), (None, 0, {}))
        with self.assertRaises(ValueError):
            self.servers.update_health(
                server.id, ping=-1, speed=None, rating=None, tests=None, filtered=None
            )
        self.assertEqual(self.servers.get_by_id(server.id), cleared)
        self.assertIsNone(
            self.servers.update_health(
                "missing", ping=1, speed=1, rating=1, tests=None, filtered=None
            )
        )
        self.assertEqual(self.servers.get_all(), [cleared])

    def stored_filtered(self, server_id: str) -> str | None:
        connection = sqlite3.connect("settings.sqlite3")
        self.addCleanup(connection.close)
        row = connection.execute(
            "SELECT filtered FROM outbound_servers WHERE id = ?", (server_id,)
        ).fetchone()
        return row[0]

    def test_reg_filters_apply_on_every_read_and_are_not_stored(self):
        ru, nl = self.server(name="RU 1"), self.server(name="NL 1")
        self.servers.add_servers([ru, nl])
        reg_filter = RegFilter(reg="RU*")
        self.store.reg_filter.add(reg_filter)
        self.assertEqual(
            [server.filtered for server in self.servers.get_all()],
            [FilterReason.BY_REG_FILTER, None],
        )
        connected = self.servers.set_connected(ru.id)
        assert connected is not None
        self.assertEqual(connected.filtered, FilterReason.BY_REG_FILTER)
        self.assertEqual(self.servers.get_connected(), connected)
        # Saving a server as it was read does not store the computed reason.
        self.servers.save(connected)
        self.assertIsNone(self.stored_filtered(ru.id))
        self.store.reg_filter.delete(reg_filter.id)
        self.assertEqual(self.servers.get_by_id(ru.id), replace(ru, is_connected=True))

    def test_by_ping_is_stored_by_checks_and_kept_by_refresh(self):
        server = self.server(name="RU 1")
        self.servers.save(server)
        failed = self.servers.update_health(
            server.id, ping=None, speed=None, rating=0, tests={}, filtered=FilterReason.BY_PING
        )
        assert failed is not None
        self.assertEqual(failed.filtered, FilterReason.BY_PING)
        self.assertEqual(self.stored_filtered(server.id), "by_ping")
        self.servers.update_servers([self.server(name="RU 1", path="/new")])
        self.assertEqual(self.servers.get_all(), [replace(failed, path="/new")])
        # A filter takes precedence over the stored reason and hides it until deleted.
        reg_filter = RegFilter(reg="RU *")
        self.store.reg_filter.add(reg_filter)
        stored = self.servers.get_by_id(server.id)
        assert stored is not None
        self.assertEqual(stored.filtered, FilterReason.BY_REG_FILTER)
        self.store.reg_filter.delete(reg_filter.id)
        stored = self.servers.get_by_id(server.id)
        assert stored is not None
        self.assertEqual(stored.filtered, FilterReason.BY_PING)
        # A successful check clears it; the reason from filters cannot be stored.
        passed = self.servers.update_health(
            server.id, ping=10, speed=1, rating=50, tests={}, filtered=None
        )
        assert passed is not None
        self.assertIsNone(passed.filtered)
        with self.assertRaises(ValueError):
            self.servers.update_health(
                server.id,
                ping=10,
                speed=1,
                rating=50,
                tests={},
                filtered=FilterReason.BY_REG_FILTER,
            )
        self.assertIsNone(self.stored_filtered(server.id))

    def test_subscription_refresh_keeps_health_of_matched_profiles(self):
        checked = self.server(name="one", ping=50, rating=3, tests={"google": True})
        other = self.server(name="two", ping=80)
        self.servers.add_servers([checked, other])
        # Freshly loaded servers carry no health; a measured value replaces the stored one.
        self.servers.update_servers(
            [self.server(name="one", path="/changed"), self.server(name="two", ping=90)]
        )
        one, two = self.servers.get_all()
        self.assertEqual(one, replace(checked, path="/changed"))
        self.assertEqual((two.id, two.ping), (other.id, 90))
        self.servers.update_servers([self.server(name="new")])
        self.assertIsNone(self.servers.get_all()[0].ping)

    def test_save_preserves_id_on_profile_refresh_and_updates_by_id(self):
        first = self.server()
        self.servers.save(first)
        refreshed = self.server(address="EXAMPLE.com.", vless_uuid=UUID(int=2))
        self.servers.save(refreshed)
        self.assertIsNone(self.servers.get_by_id(refreshed.id))
        self.assertEqual(self.servers.get_all(), [replace(refreshed, id=first.id)])
        renamed = replace(first, name="Renamed", port=8443)
        self.servers.save(renamed)
        self.assertEqual(self.servers.get_by_id(first.id), renamed)
        self.assertTrue(self.servers.delete(first.id))
        self.assertFalse(self.servers.delete(first.id))
        self.assertIsNone(self.servers.get_by_id(first.id))

    def test_full_replacement_order_deduplication_stable_ids_and_clear(self):
        first, second, removed = (self.server(name=name) for name in ("one", "two", "removed"))
        self.servers.add_servers([first, second, removed])
        refreshed = self.server(name="one", path="/changed")
        self.servers.update_servers([second, first, refreshed])
        self.assertEqual(self.servers.get_all(), [second, replace(refreshed, id=first.id)])
        self.assertIsNone(self.servers.get_by_id(removed.id))
        self.servers.update_servers([])
        self.assertEqual(self.servers.get_all(), [])

    def test_failed_batch_rolls_back_including_replacement_deletion(self):
        first, second = self.server(name="one"), self.server(name="two")
        self.servers.add_servers([first, second])
        ambiguous = replace(second, name=first.name)
        with self.assertRaises(sqlite3.IntegrityError):
            self.servers.save(ambiguous)
        with self.assertRaises(sqlite3.IntegrityError):
            self.servers.add_servers([self.server(name="new"), ambiguous])
        self.assertEqual(self.servers.get_all(), [first, second])
        duplicate_id = replace(first, name="different profile")
        with self.assertRaises(sqlite3.IntegrityError):
            self.servers.update_servers([first, duplicate_id])
        self.assertEqual(self.servers.get_all(), [first, second])
        self.store._connection.execute("PRAGMA query_only = ON")
        with self.assertRaises(sqlite3.OperationalError):
            self.servers.delete(first.id)
        self.store._connection.execute("PRAGMA query_only = OFF")

    def test_snapshots_and_external_database_changes(self):
        server = self.server(stream_options={"nested": {"value": 1}})
        self.servers.save(server)
        snapshot = self.servers.get_by_id(server.id)
        assert snapshot is not None
        snapshot.stream_options.clear()
        self.servers.get_all().clear()
        self.assertEqual(self.servers.get_by_id(server.id), server)
        connection = sqlite3.connect("settings.sqlite3")
        self.addCleanup(connection.close)
        with connection:
            connection.execute("DELETE FROM outbound_servers WHERE id = ?", (server.id,))
        self.assertIsNone(self.servers.get_by_id(server.id))
        self.assertEqual(self.servers.get_all(), [])

    def test_fields_are_individual_columns_and_protocol_changes_clear_old_settings(self):
        server = self.server(allow_insecure=False, alpn=("h2",))
        self.servers.save(server)
        connection = sqlite3.connect("settings.sqlite3")
        self.addCleanup(connection.close)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(outbound_servers)")}
        self.assertNotIn("payload", columns)
        self.assertNotIn("settings", columns)
        row = connection.execute(
            "SELECT name, address, port, typeof(port), vless_uuid, vless_encryption, "
            "allow_insecure, alpn, shadowsocks_password, hysteria_auth FROM outbound_servers"
        ).fetchone()
        self.assertEqual(
            row,
            (
                server.name,
                server.address,
                443,
                "integer",
                str(UUID(int=1)),
                "none",
                0,
                '["h2"]',
                None,
                None,
            ),
        )
        switched = self.other_protocol(
            id=server.id,
            protocol=OutboundProtocol.SHADOWSOCKS,
            shadowsocks_password="password",
            shadowsocks_method=ShadowsocksMethod.AES_256_GCM,
            alpn=("h2",),
        )
        self.servers.save(switched)
        self.assertEqual(self.servers.get_by_id(server.id), switched)
        row = connection.execute(
            "SELECT vless_uuid, vless_encryption, vless_flow, vless_extra, "
            "shadowsocks_password, shadowsocks_udp_over_tcp, shadowsocks_uot_version, "
            "allow_insecure FROM outbound_servers"
        ).fetchone()
        self.assertEqual(row, (None, None, None, None, "password", 0, None, None))
        with connection:
            connection.execute("UPDATE outbound_servers SET path = '/updated'")
        self.assertEqual(self.servers.get_by_id(server.id), replace(switched, path="/updated"))
