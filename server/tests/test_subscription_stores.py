import asyncio
import base64
import json
import unittest
from contextlib import chdir
from copy import deepcopy
from dataclasses import replace
from secrets import token_hex
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from server.models import (
    OutboundProtocol,
    OutboundServer,
    SubscriptionLink,
    XhttpMode,
)
from server.settings_store import SettingsStore
from server.subscription_loader import SubscriptionError, load_subscription

URI = (
    "vless://00000000-0000-0000-0000-000000000001@EXAMPLE.com:443"
    "?type=xhttp&security=reality&pbk=example&sid=12&mode=stream-one"
    "&path=%2Ftest&x-provider=keep#Test%20server"
)


def _load_servers(body: str, subscription_id: str) -> list[OutboundServer]:
    link = SubscriptionLink(url="https://example.com/sub", id=subscription_id)
    with patch("server.subscription_loader._download", return_value=body):
        return asyncio.run(load_subscription(link))


class SubscriptionParsingTests(unittest.TestCase):
    def test_plain_and_base64(self):
        plain = _load_servers(URI, "sub")
        encoded = base64.b64encode(URI.encode()).decode().rstrip("=")
        decoded = _load_servers(encoded, "sub")
        self.assertNotEqual(decoded[0].id, plain[0].id)
        self.assertRegex(decoded[0].id, r"^[0-9a-f]{12}$")
        decoded[0].id = plain[0].id
        self.assertEqual(decoded, plain)
        server = plain[0]
        self.assertIs(server.protocol, OutboundProtocol.VLESS)
        self.assertEqual(server.vless_uuid, UUID(int=1))
        self.assertEqual(server.xhttp_mode, XhttpMode.STREAM_ONE)
        self.assertEqual(server.name, "Test server")
        self.assertEqual(server.path, "/test")
        self.assertEqual(server.extra_params, {"x-provider": "keep"})
        self.assertEqual(server.subscription_id, "sub")

    def test_json_multiple_protocols_and_profiles(self):
        outbound = {
            "protocol": "vless",
            "tag": "proxy",
            "settings": {
                "vnext": [
                    {
                        "address": "example.com",
                        "port": 443,
                        "users": [{"id": str(UUID(int=1))}, {"id": str(UUID(int=2))}],
                    }
                ]
            },
            "streamSettings": {
                "network": "xhttp",
                "security": "reality",
                "xhttpSettings": {"mode": "packet-up", "extra": {"xmux": {"maxConnections": 2}}},
            },
        }
        body = json.dumps(
            [
                {"remarks": "Profile", "outbounds": [outbound, {"protocol": "freedom"}]},
                {
                    "outbounds": [
                        {
                            "protocol": "shadowsocks",
                            "settings": {
                                "servers": [
                                    {
                                        "address": "example.net",
                                        "port": 8443,
                                        "password": "secret",
                                        "method": "chacha20-poly1305",
                                        "uot": True,
                                        "UoTVersion": 2,
                                    }
                                ]
                            },
                        },
                        {
                            "protocol": "hysteria",
                            "settings": {"address": "example.org", "port": 443, "version": 2},
                            "streamSettings": {
                                "network": "hysteria",
                                "security": "tls",
                                "hysteriaSettings": {"version": 2, "auth": "auth-secret"},
                            },
                        },
                    ]
                },
            ]
        )
        servers = _load_servers(body, "sub")
        self.assertEqual(len(servers), 4)
        self.assertIs(servers[2].protocol, OutboundProtocol.SHADOWSOCKS)
        self.assertIs(servers[3].protocol, OutboundProtocol.HYSTERIA)
        self.assertEqual(servers[3].hysteria_auth, "auth-secret")
        self.assertIsNone(servers[3].vless_uuid)
        self.assertEqual(servers[2].shadowsocks_uot_version, 2)
        self.assertEqual(servers[0].stream_options, outbound["streamSettings"])
        self.assertEqual(servers[0].source_tag, "proxy")

    def test_invalid_response_is_not_an_empty_subscription(self):
        for body in (
            "<html>error</html>",
            "{}",
            URI.replace(":443", ":99999"),
            URI + "\ntrojan://unsupported",
            URI.replace("type=xhttp", "type=unknown"),
        ):
            with self.subTest(body=body), self.assertRaises(SubscriptionError):
                _load_servers(body, "sub")

    def test_ipv6_and_empty_subscription(self):
        server = _load_servers(URI.replace("EXAMPLE.com", "[2001:db8::1]"), "sub")[0]
        self.assertEqual(server.address, "2001:db8::1")
        self.assertEqual(_load_servers("[]", "sub"), [])


class ServersStoreTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(chdir(directory))
        self.store = self.enterContext(SettingsStore()).outbound_server

    def test_update_parameters_without_duplicate(self):
        original = _load_servers(URI, "sub")[0]
        updated = deepcopy(original)
        updated.address = "example.com."
        updated.vless_uuid = UUID(int=2)
        store = self.store
        store.add_servers([original])
        store.add_servers([updated])
        self.assertEqual(len(store.get_all()), 1)
        saved = store.get_all()[0]
        self.assertEqual(saved.vless_uuid, UUID(int=2))
        updated.name = "External mutation"
        store.get_all()[0].name = "Snapshot mutation"
        self.assertEqual(store.get_all()[0].name, original.name)

    def test_distinct_subscription_protocol_port_and_replace(self):
        servers = [_load_servers(URI, "a")[0], _load_servers(URI, "b")[0]]
        other_port = deepcopy(servers[0])
        other_port.id = token_hex(6)
        other_port.port = 8443
        other_protocol = replace(
            servers[0],
            id=token_hex(6),
            protocol=OutboundProtocol.HYSTERIA,
            hysteria_auth="test",
            vless_uuid=None,
            vless_encryption=None,
            vless_flow=None,
            vless_extra=None,
        )
        store = self.store
        store.add_servers(servers + [other_port, other_protocol])
        self.assertEqual(len(store.get_all()), 4)
        store.update_servers([servers[0], servers[0]])
        self.assertEqual(len(store.get_all()), 1)
        store.update_servers([])
        self.assertEqual(store.get_all(), [])

    def test_distinct_names_and_tags_on_same_endpoint_survive(self):
        first = _load_servers(URI, "sub")[0]
        second = deepcopy(first)
        second.id = token_hex(6)
        second.name = "Another location"
        second.server_name = "other.example.com"
        third = deepcopy(first)
        third.id = token_hex(6)
        third.source_tag = "another-outbound"
        store = self.store
        store.add_servers([first, second, third])
        self.assertEqual(len(store.get_all()), 3)
        replacement = deepcopy(second)
        replacement.vless_uuid = UUID(int=2)
        store.add_servers([replacement])
        self.assertEqual(len(store.get_all()), 3)
        saved = store.get_all()[1]
        self.assertEqual(saved.vless_uuid, UUID(int=2))
        store.update_servers([first, second, third])
        self.assertEqual(len(store.get_all()), 3)

    def test_equivalent_ipv6(self):
        store = self.store
        store.add_servers(
            [
                OutboundServer(
                    name="IP",
                    address=address,
                    port=443,
                    protocol=OutboundProtocol.VLESS,
                    vless_uuid=UUID(int=1),
                )
                for address in ("2001:db8::1", "2001:0db8:0:0:0:0:0:1")
            ]
        )
        self.assertEqual(len(store.get_all()), 1)
