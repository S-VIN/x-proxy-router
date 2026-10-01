"""Shared access to settings in the working directory's SQLite database."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import fields, replace
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar, Self
from uuid import UUID

from .models.inbound_server import DEFAULT_PROXY_PORT, InboundServer, InboundType
from .models.outbound_server import (
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
from .models.outbound_test import OutboundTest, OutboundTestRule
from .models.reg_filter import RegFilter
from .models.routing_rule import RoutingAction, RoutingRule, placed, without
from .models.server_settings import ServerSettings
from .models.subscription_link import SubscriptionLink


class ServerSettingsStore:
    """The single ServerSettings row, created with defaults when the table is created."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        with self._connection:
            # CHECK keeps the table to one row with id 0, even for other connections.
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS server_settings ("
                "id INTEGER PRIMARY KEY NOT NULL CHECK (id = 0), "
                "subscription_refresh_interval INTEGER NOT NULL, "
                "last_subscription_refresh TEXT, "
                "auto_connect INTEGER NOT NULL DEFAULT 0)"
            )
            # Databases created before auto_connect get the column, with the mode off.
            columns = {
                row[1] for row in self._connection.execute("PRAGMA table_info(server_settings)")
            }
            if "auto_connect" not in columns:
                self._connection.execute(
                    "ALTER TABLE server_settings ADD COLUMN auto_connect INTEGER NOT NULL DEFAULT 0"
                )
            # Dataclass defaults fill a missing row; an existing row is kept.
            self._write(ServerSettings(), "INSERT OR IGNORE")

    def get(self) -> ServerSettings:
        row = self._connection.execute(
            "SELECT subscription_refresh_interval, last_subscription_refresh, auto_connect "
            "FROM server_settings WHERE id = 0"
        ).fetchone()
        if row is None:
            raise LookupError("The server_settings row was deleted outside the application")
        interval, refreshed, auto_connect = row
        return ServerSettings(
            subscription_refresh_interval=interval,
            last_subscription_refresh=(
                datetime.fromisoformat(refreshed) if refreshed is not None else None
            ),
            auto_connect=bool(auto_connect),
        )

    def save(self, settings: ServerSettings) -> None:
        """Replace the stored settings; the datetime is stored as ISO 8601 in UTC."""
        with self._connection:
            self._write(settings, "INSERT OR REPLACE")

    def _write(self, settings: ServerSettings, statement: str) -> None:
        refreshed = settings.last_subscription_refresh
        self._connection.execute(
            f"{statement} INTO server_settings "
            "(id, subscription_refresh_interval, last_subscription_refresh, auto_connect) "
            "VALUES (?, ?, ?, ?)",
            (
                settings.id,
                settings.subscription_refresh_interval,
                refreshed.isoformat() if refreshed is not None else None,
                settings.auto_connect,
            ),
        )


class SubscriptionLinkStore:
    """Subscription settings sharing the connection owned by SettingsStore."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        with self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS subscription_links ("
                "id TEXT PRIMARY KEY NOT NULL, url TEXT NOT NULL UNIQUE)"
            )

    def get_all(self) -> list[SubscriptionLink]:
        """Return a snapshot of all subscription links in insertion order."""
        return [
            SubscriptionLink(id=id_, url=url)
            for id_, url in self._connection.execute(
                "SELECT id, url FROM subscription_links ORDER BY rowid"
            )
        ]

    def get_by_id(self, subscription_id: str) -> SubscriptionLink | None:
        """Return the link with this id, or None if it does not exist."""
        row = self._connection.execute(
            "SELECT id, url FROM subscription_links WHERE id = ?", (subscription_id,)
        ).fetchone()
        return SubscriptionLink(id=row[0], url=row[1]) if row is not None else None

    def save(self, subscription: SubscriptionLink) -> None:
        """Insert a link or update its URL by id, preserving insertion order.

        A URL already used by another id raises sqlite3.IntegrityError.
        """
        with self._connection:
            self._connection.execute(
                "INSERT INTO subscription_links (id, url) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET url = excluded.url",
                (subscription.id, subscription.url),
            )

    def delete(self, subscription_id: str) -> bool:
        """Delete a link by id; return False if it did not exist."""
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM subscription_links WHERE id = ?", (subscription_id,)
            )
        return cursor.rowcount > 0


class RegFilterStore:
    """Filters of outbound servers by name, sharing the connection owned by SettingsStore."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        with self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS reg_filters ("
                "id TEXT PRIMARY KEY NOT NULL, reg TEXT NOT NULL UNIQUE)"
            )

    def get_all(self) -> list[RegFilter]:
        """Return a snapshot of all filters in insertion order."""
        return [
            RegFilter(id=id_, reg=reg)
            for id_, reg in self._connection.execute(
                "SELECT id, reg FROM reg_filters ORDER BY rowid"
            )
        ]

    def add(self, reg_filter: RegFilter) -> None:
        """Insert a filter; an id or regular expression already stored raises
        sqlite3.IntegrityError.
        """
        with self._connection:
            self._connection.execute(
                "INSERT INTO reg_filters (id, reg) VALUES (?, ?)", (reg_filter.id, reg_filter.reg)
            )

    def delete(self, filter_id: str) -> bool:
        """Delete a filter by id; return False if it did not exist."""
        with self._connection:
            cursor = self._connection.execute("DELETE FROM reg_filters WHERE id = ?", (filter_id,))
        return cursor.rowcount > 0


class OutboundTestStore:
    """Tests of outbound servers, sharing the connection owned by SettingsStore."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        with self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS outbound_tests ("
                "id TEXT PRIMARY KEY NOT NULL, url TEXT NOT NULL UNIQUE, rule TEXT NOT NULL)"
            )

    def get_all(self) -> list[OutboundTest]:
        """Return a snapshot of all tests in insertion order."""
        return [
            OutboundTest(id=id_, url=url, rule=OutboundTestRule(rule))
            for id_, url, rule in self._connection.execute(
                "SELECT id, url, rule FROM outbound_tests ORDER BY rowid"
            )
        ]

    def add(self, test: OutboundTest) -> None:
        """Insert a test; an id or URL already stored raises sqlite3.IntegrityError."""
        with self._connection:
            self._connection.execute(
                "INSERT INTO outbound_tests (id, url, rule) VALUES (?, ?, ?)",
                (test.id, test.url, test.rule.value),
            )

    def delete(self, test_id: str) -> bool:
        """Delete a test by id; return False if it did not exist."""
        with self._connection:
            cursor = self._connection.execute("DELETE FROM outbound_tests WHERE id = ?", (test_id,))
        return cursor.rowcount > 0


class InboundServerStore:
    """Listeners of the core, sharing the connection owned by SettingsStore.

    Creating the table also stores the default inbound: a proxy on
    127.0.0.1:DEFAULT_PROXY_PORT. Deleted, it does not come back.
    """

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        with self._connection:
            created = (
                self._connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'inbound_servers'"
                ).fetchone()
                is None
            )
            # Ports are unique among inbounds; NULL ports of other types do not conflict.
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS inbound_servers ("
                "id TEXT PRIMARY KEY NOT NULL, "
                "type TEXT NOT NULL, "
                "enabled INTEGER NOT NULL, "
                "proxy_listen TEXT, "
                "proxy_port INTEGER UNIQUE, "
                "proxy_username TEXT, "
                "proxy_password TEXT, "
                "error TEXT)"
            )
            if created:
                self._write(InboundServer(type=InboundType.PROXY, proxy_port=DEFAULT_PROXY_PORT))

    def _read(self, query: str, parameters: tuple[str, ...] = ()) -> list[InboundServer]:
        cursor = self._connection.execute(query, parameters)
        cursor.row_factory = sqlite3.Row
        inbounds = []
        for row in cursor:
            values: dict[str, Any] = {item.name: row[item.name] for item in fields(InboundServer)}
            values["type"] = InboundType(values["type"])
            values["enabled"] = bool(values["enabled"])
            inbounds.append(InboundServer(**values))
        return inbounds

    def get_all(self) -> list[InboundServer]:
        """Return a snapshot of all inbounds in insertion order."""
        return self._read("SELECT * FROM inbound_servers ORDER BY rowid")

    def get_by_id(self, inbound_id: str) -> InboundServer | None:
        inbounds = self._read("SELECT * FROM inbound_servers WHERE id = ?", (inbound_id,))
        return inbounds[0] if inbounds else None

    def save(self, inbound: InboundServer) -> None:
        """Insert an inbound or update it by id, preserving insertion order.

        A port already used by another inbound raises sqlite3.IntegrityError.
        """
        with self._connection:
            self._write(inbound)

    def _write(self, inbound: InboundServer) -> None:
        values = {item.name: getattr(inbound, item.name) for item in fields(InboundServer)}
        # Column names come only from the model's fields.
        columns = ", ".join(values)
        parameters = ", ".join(f":{column}" for column in values)
        assignments = ", ".join(
            f"{column} = excluded.{column}" for column in values if column != "id"
        )
        self._connection.execute(
            f"INSERT INTO inbound_servers ({columns}) VALUES ({parameters}) "
            f"ON CONFLICT(id) DO UPDATE SET {assignments}",
            values,
        )

    def set_error(self, inbound_id: str, error: str | None) -> None:
        """Replace the error the server keeps for the inbound; other fields are kept."""
        with self._connection:
            self._connection.execute(
                "UPDATE inbound_servers SET error = ? WHERE id = ?", (error, inbound_id)
            )

    def delete(self, inbound_id: str) -> bool:
        """Delete an inbound by id; return False if it did not exist."""
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM inbound_servers WHERE id = ?", (inbound_id,)
            )
        return cursor.rowcount > 0


class RoutingRuleStore:
    """Routing rules numbered 1..N by priority, sharing the connection owned by SettingsStore.

    Changes renumber the rules the way models.routing_rule.placed and without do.
    """

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        with self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS routing_rules ("
                "id TEXT PRIMARY KEY NOT NULL, "
                "priority INTEGER NOT NULL UNIQUE, "
                "reg TEXT NOT NULL UNIQUE, "
                "action TEXT NOT NULL)"
            )

    def _read(self, query: str, parameters: tuple[str, ...] = ()) -> list[RoutingRule]:
        return [
            RoutingRule(id=id_, priority=priority, reg=reg, action=RoutingAction(action))
            for id_, priority, reg, action in self._connection.execute(query, parameters)
        ]

    def get_all(self) -> list[RoutingRule]:
        """Return a snapshot of all rules by priority."""
        return self._read("SELECT id, priority, reg, action FROM routing_rules ORDER BY priority")

    def get_by_id(self, rule_id: str) -> RoutingRule | None:
        rules = self._read(
            "SELECT id, priority, reg, action FROM routing_rules WHERE id = ?", (rule_id,)
        )
        return rules[0] if rules else None

    def save(self, rule: RoutingRule) -> None:
        """Insert a rule or update it by id, putting it at its priority.

        The other rules move to keep 1..N; a priority more than one past the
        last rule raises RoutingRuleFieldError, a pattern of another rule
        sqlite3.IntegrityError.
        """
        with self._connection:
            self._write_all(placed(self.get_all(), rule))

    def delete(self, rule_id: str) -> bool:
        """Delete a rule by id, moving the rules after it up; return False if it did not exist."""
        with self._connection:
            rules = self.get_all()
            remaining = without(rules, rule_id)
            if len(remaining) == len(rules):
                return False
            self._write_all(remaining)
        return True

    def _write_all(self, rules: list[RoutingRule]) -> None:
        # Rewriting the few rules avoids transient duplicates of the unique priorities.
        self._connection.execute("DELETE FROM routing_rules")
        self._connection.executemany(
            "INSERT INTO routing_rules (id, priority, reg, action) VALUES (?, ?, ?, ?)",
            [(rule.id, rule.priority, rule.reg, rule.action.value) for rule in rules],
        )


def _server_key(server: OutboundServer) -> str:
    address = server.address.strip().strip("[]")
    try:
        address = ip_address(address).compressed
    except ValueError:
        address = address.rstrip(".").encode("idna").decode("ascii").lower()
    return json.dumps(
        [
            server.subscription_id,
            server.name,
            server.source_tag,
            server.protocol,
            address,
            server.port,
        ],
        ensure_ascii=False,
    )


# Columns decoded from SQLite values; the others are stored as is.
_SERVER_COLUMN_TYPES = {
    "protocol": OutboundProtocol,
    "transport": OutboundTransport,
    "security": OutboundSecurity,
    "alpn": lambda value: tuple(json.loads(value)),
    "allow_insecure": bool,
    "grpc_mode": GrpcMode,
    "xhttp_mode": XhttpMode,
    "stream_options": json.loads,
    "extra_params": json.loads,
    "vless_uuid": UUID,
    "vless_flow": VlessFlow,
    "vless_extra": json.loads,
    "shadowsocks_method": ShadowsocksMethod,
    "shadowsocks_udp_over_tcp": bool,
    "shadowsocks_uot_version": UotVersion,
    "shadowsocks_extra": json.loads,
    "hysteria_extra": json.loads,
    "tests": json.loads,
    "filtered": FilterReason,
    "is_connected": bool,
}

# Set by the server's checks, not loaded from subscriptions; filtered holds by_ping.
_HEALTH_FIELDS = ("ping", "speed", "rating", "tests", "filtered")


def _server_columns(server: OutboundServer) -> dict[str, str | int | None]:
    """One column per model field; only collections need JSON encoding."""
    values: dict[str, str | int | None] = {"profile_key": _server_key(server)}
    for item in fields(OutboundServer):
        value = getattr(server, item.name)
        if isinstance(value, dict | tuple):
            value = json.dumps(value)
        elif isinstance(value, UUID):
            value = str(value)
        values[item.name] = value
    # Computed from the filters on every read, so the column never holds it.
    if values["filtered"] == FilterReason.BY_REG_FILTER:
        values["filtered"] = None
    return values


def _server_from_row(row: sqlite3.Row, reg_filters: Sequence[RegFilter] = ()) -> OutboundServer:
    """The stored server; a name matching one of reg_filters gets filtered = by_reg_filter."""
    values: dict[str, Any] = {}
    for item in fields(OutboundServer):
        value = row[item.name]
        decode = _SERVER_COLUMN_TYPES.get(item.name)
        values[item.name] = decode(value) if decode is not None and value is not None else value
    if any(reg_filter.matches(values["name"]) for reg_filter in reg_filters):
        values["filtered"] = FilterReason.BY_REG_FILTER
    return OutboundServer(**values)


class OutboundServerStore:
    """Persist named profiles; refresh matching profiles without changing their ids.

    Servers are read with filtered = by_reg_filter if their name matches one of
    the stored filters; otherwise filtered is the stored value (by_ping). So a
    change of the filters applies at once, without writing the servers.
    """

    def __init__(self, connection: sqlite3.Connection, reg_filters: RegFilterStore):
        self._connection = connection
        self._reg_filters = reg_filters
        with connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS outbound_servers (
                    id TEXT PRIMARY KEY NOT NULL,
                    profile_key TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    address TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    subscription_id TEXT,
                    source_tag TEXT,
                    protocol TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    security TEXT NOT NULL,
                    server_name TEXT,
                    fingerprint TEXT,
                    alpn TEXT NOT NULL,
                    public_key TEXT,
                    short_id TEXT,
                    spider_x TEXT,
                    allow_insecure INTEGER,
                    host TEXT,
                    path TEXT,
                    service_name TEXT,
                    grpc_mode TEXT,
                    xhttp_mode TEXT,
                    stream_options TEXT NOT NULL,
                    extra_params TEXT NOT NULL,
                    vless_uuid TEXT,
                    vless_encryption TEXT,
                    vless_flow TEXT,
                    vless_extra TEXT,
                    shadowsocks_password TEXT,
                    shadowsocks_method TEXT,
                    shadowsocks_udp_over_tcp INTEGER,
                    shadowsocks_uot_version INTEGER,
                    shadowsocks_extra TEXT,
                    hysteria_auth TEXT,
                    hysteria_version INTEGER,
                    hysteria_extra TEXT,
                    ping INTEGER,
                    speed INTEGER,
                    rating INTEGER,
                    tests TEXT,
                    filtered TEXT,
                    is_connected INTEGER NOT NULL
                )"""
            )
            # At most one server is connected.
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS outbound_servers_connected "
                "ON outbound_servers (is_connected) WHERE is_connected"
            )

    def _read(self, query: str, parameters: tuple[str, ...] = ()) -> list[OutboundServer]:
        reg_filters = self._reg_filters.get_all()
        cursor = self._connection.execute(query, parameters)
        cursor.row_factory = sqlite3.Row
        return [_server_from_row(row, reg_filters) for row in cursor]

    def get_all(self) -> list[OutboundServer]:
        return self._read("SELECT * FROM outbound_servers ORDER BY rowid")

    def get_by_id(self, server_id: str) -> OutboundServer | None:
        servers = self._read("SELECT * FROM outbound_servers WHERE id = ?", (server_id,))
        return servers[0] if servers else None

    def _write(self, server: OutboundServer, *, update: bool = False) -> None:
        values = _server_columns(server)
        # Column names come only from the fixed Python definition above.
        columns = ", ".join(values)
        parameters = ", ".join(f":{column}" for column in values)
        statement = f"INSERT INTO outbound_servers ({columns}) VALUES ({parameters})"
        if update:
            assignments = ", ".join(
                f"{column} = excluded.{column}" for column in values if column != "id"
            )
            statement += f" ON CONFLICT(id) DO UPDATE SET {assignments}"
        self._connection.execute(statement, values)

    def save(self, server: OutboundServer) -> None:
        """Update by id or profile key, or insert. Conflicting matches are rejected."""
        with self._connection:
            self._save(server)

    def _save(self, server: OutboundServer) -> None:
        key = _server_key(server)
        matches = self._connection.execute(
            "SELECT id FROM outbound_servers WHERE id = ? OR profile_key = ?",
            (server.id, key),
        ).fetchall()
        if len(matches) > 1:
            raise sqlite3.IntegrityError("Server id and profile key match different records")
        server_id = matches[0][0] if matches else server.id
        self._write(replace(server, id=server_id), update=True)

    def update_health(
        self,
        server_id: str,
        *,
        ping: int | None,
        speed: int | None,
        rating: int | None,
        tests: dict[str, bool] | None,
        filtered: FilterReason | None,
    ) -> OutboundServer | None:
        """Replace check results of the stored server; other fields keep stored values.

        filtered is the reason given by the check: by_ping or None. A matching
        filter still shows by_reg_filter in the returned server.
        Returns the updated server, or None if it was deleted meanwhile (nothing is written).
        """
        if filtered == FilterReason.BY_REG_FILTER:
            raise ValueError("by_reg_filter is computed from the filters and cannot be stored")
        with self._connection:
            server = self.get_by_id(server_id)
            if server is None:
                return None
            # replace() validates the values before they are written.
            replace(server, ping=ping, speed=speed, rating=rating, tests=tests, filtered=filtered)
            self._connection.execute(
                "UPDATE outbound_servers SET ping = ?, speed = ?, rating = ?, tests = ?, "
                "filtered = ? WHERE id = ?",
                (
                    ping,
                    speed,
                    rating,
                    json.dumps(tests) if tests is not None else None,
                    filtered,
                    server_id,
                ),
            )
        return self.get_by_id(server_id)

    def get_connected(self) -> OutboundServer | None:
        """The server with is_connected, or None."""
        servers = self._read("SELECT * FROM outbound_servers WHERE is_connected")
        return servers[0] if servers else None

    def set_connected(self, server_id: str | None) -> OutboundServer | None:
        """Mark only this server as connected; None disconnects all.

        Returns the connected server, or None if there is no such server
        (then no server is marked).
        """
        with self._connection:
            self._connection.execute(
                "UPDATE outbound_servers SET is_connected = 0 WHERE is_connected"
            )
            if server_id is not None:
                self._connection.execute(
                    "UPDATE outbound_servers SET is_connected = 1 WHERE id = ?", (server_id,)
                )
        return self.get_by_id(server_id) if server_id is not None else None

    def delete(self, server_id: str) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM outbound_servers WHERE id = ?", (server_id,)
            )
        return cursor.rowcount > 0

    def add_servers(self, servers: list[OutboundServer]) -> None:
        """Merge the batch atomically; the last matching profile wins."""
        with self._connection:
            for server in servers:
                self._save(server)

    def update_servers(self, servers: list[OutboundServer]) -> None:
        """Replace the entire collection atomically, preserving ids of matched profiles.

        Matched profiles also keep stored health values the new servers leave as None,
        so a subscription refresh does not erase check results (by_ping included),
        and keep is_connected.
        """
        with self._connection:
            # Acquire the write transaction before reading ids for this replacement.
            self._connection.execute("BEGIN IMMEDIATE")
            cursor = self._connection.execute("SELECT * FROM outbound_servers")
            cursor.row_factory = sqlite3.Row
            existing = {row["profile_key"]: _server_from_row(row) for row in cursor}
            replacement = {}
            for server in servers:
                key = _server_key(server)
                stored = existing.get(key)
                if stored is not None:
                    kept = {
                        name: getattr(stored, name)
                        for name in _HEALTH_FIELDS
                        if getattr(server, name) is None
                    }
                    server = replace(server, id=stored.id, is_connected=stored.is_connected, **kept)
                replacement[key] = server
            self._connection.execute("DELETE FROM outbound_servers")
            for server in replacement.values():
                # A shared id for different profiles is ambiguous, never silently drop one.
                self._write(server)


def _move_outbound_tests(connection: sqlite3.Connection) -> None:
    """Move tests of databases from before OutboundTest.id to their own table.

    Such databases keep them in server_settings.outbound_tests as a JSON array of
    {url, alias, rule}, and the servers' results by alias. The tests get ids, the
    results are keyed by them, and the column is dropped. A test whose URL is
    already stored keeps the stored id.
    """
    columns = {row[1] for row in connection.execute("PRAGMA table_info(server_settings)")}
    if "outbound_tests" not in columns:
        return
    with connection:
        row = connection.execute("SELECT outbound_tests FROM server_settings").fetchone()
        ids = {}
        for item in json.loads(row[0]) if row is not None else []:
            test = OutboundTest(url=item["url"], rule=OutboundTestRule(item["rule"]))
            connection.execute(
                "INSERT OR IGNORE INTO outbound_tests (id, url, rule) VALUES (?, ?, ?)",
                (test.id, test.url, test.rule.value),
            )
            (ids[item["alias"]],) = connection.execute(
                "SELECT id FROM outbound_tests WHERE url = ?", (test.url,)
            ).fetchone()
        servers = connection.execute(
            "SELECT id, tests FROM outbound_servers WHERE tests IS NOT NULL"
        ).fetchall()
        for server_id, tests in servers:
            results = {
                ids[alias]: passed for alias, passed in json.loads(tests).items() if alias in ids
            }
            connection.execute(
                "UPDATE outbound_servers SET tests = ? WHERE id = ?",
                (json.dumps(results), server_id),
            )
        connection.execute("ALTER TABLE server_settings DROP COLUMN outbound_tests")


class SettingsStore:
    """One active store per process, with entity-specific access to SQLite.

    Call methods sequentially from the thread that first created the store.
    Models are read from the database without caching.
    """

    _instance: ClassVar[Self | None] = None
    _connection: sqlite3.Connection
    server_settings: ServerSettingsStore
    subscription_link: SubscriptionLinkStore
    reg_filter: RegFilterStore
    outbound_test: OutboundTestStore
    outbound_server: OutboundServerStore
    inbound_server: InboundServerStore
    routing_rule: RoutingRuleStore

    def __new__(cls) -> Self:
        if cls._instance is None:
            instance = super().__new__(cls)
            # SQLite creates the file if it does not exist.
            instance._connection = sqlite3.connect(Path.cwd() / "settings.sqlite3")
            try:
                instance.server_settings = ServerSettingsStore(instance._connection)
                instance.subscription_link = SubscriptionLinkStore(instance._connection)
                instance.reg_filter = RegFilterStore(instance._connection)
                instance.outbound_test = OutboundTestStore(instance._connection)
                instance.outbound_server = OutboundServerStore(
                    instance._connection, instance.reg_filter
                )
                instance.inbound_server = InboundServerStore(instance._connection)
                instance.routing_rule = RoutingRuleStore(instance._connection)
                _move_outbound_tests(instance._connection)
            except Exception:
                instance._connection.close()
                raise
            cls._instance = instance
        return cls._instance

    def close(self) -> None:
        """Close the shared store. The next SettingsStore() call opens a new one."""
        self._connection.close()
        if type(self)._instance is self:
            type(self)._instance = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
