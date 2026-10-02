import asyncio
import socket
import unittest
from copy import deepcopy
from dataclasses import replace
from typing import Any
from unittest.mock import patch
from uuid import UUID

from server.cores import CoreClient, CoreProcessManagerInterface, InboundError
from server.cores.mihomo.mihomo_client import MihomoClient, inbound_config
from server.cores.mihomo.mihomo_process_manager import MihomoError
from server.cores.mihomo.outbound_config import outbound_config
from server.models import (
    CoreState,
    InboundServer,
    InboundType,
    OutboundProtocol,
    OutboundSecurity,
    OutboundServer,
    OutboundTransport,
    RoutingAction,
    RoutingRule,
    ShadowsocksMethod,
)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def remote(port=12345):
    return OutboundServer(
        name="sample",
        address="127.0.0.1",
        port=port,
        protocol=OutboundProtocol.VLESS,
        vless_uuid=UUID(int=1),
    )


def inbound(**values: Any) -> InboundServer:
    values.setdefault("proxy_port", free_port())
    return InboundServer(type=InboundType.PROXY, **values)


class MihomoConfigTests(unittest.TestCase):
    def test_translation_and_no_mutation(self):
        model = remote()
        model.transport = OutboundTransport.XHTTP
        model.stream_options = {
            "xhttpSettings": {
                "path": "/proxy",
                "extra": {"scMaxEachPostBytes": 1000000, "xmux": {"maxConcurrency": "8-16"}},
            }
        }
        before = deepcopy(model)
        config = outbound_config(model, "out")
        self.assertEqual(config["xhttp-opts"]["path"], "/proxy")
        self.assertEqual(config["xhttp-opts"]["sc-max-each-post-bytes"], "1000000")
        self.assertEqual(config["xhttp-opts"]["reuse-settings"]["max-concurrency"], "8-16")
        self.assertEqual(model, before)

    def test_unknown_extensions_fail_without_credentials(self):
        model = remote()
        model.stream_options = {"sockopt": {"secret": "password-never-log"}}
        with self.assertRaises(ValueError) as raised:
            outbound_config(model, "out")
        self.assertNotIn("password-never-log", str(raised.exception))
        # The client checks a server without a running core.
        MihomoClient().check_outbound_server_config(remote())
        with self.assertRaises(ValueError):
            MihomoClient().check_outbound_server_config(model)

    def test_inbound_listener(self):
        listener = inbound(proxy_listen="::", proxy_username="user", proxy_password="secret")
        self.assertEqual(
            inbound_config(listener),
            {
                "name": listener.id,
                "type": "mixed",
                "listen": "::",
                "port": listener.proxy_port,
                "udp": True,
                "users": [{"username": "user", "password": "secret"}],
            },
        )
        self.assertNotIn("users", inbound_config(inbound()))
        MihomoClient().check_inbound_config(listener)


class MihomoIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_and_delete_servers(self):
        c = self.client
        await c.service_start()
        first, second = remote(), remote()
        await c.outbound_register([first, second])
        await c.outbound_connect(first.id)
        await c.test_connect(second.id)
        await c.outbound_register([first])
        proxies = (await c.rest_client.get_proxies())["proxies"]
        self.assertIn(first.id, proxies)
        self.assertNotIn(second.id, proxies)
        for role in ("main", "test"):
            self.assertEqual(proxies[role]["all"], ["REJECT", first.id])
            self.assertEqual(proxies[role]["now"], "REJECT")
        with self.assertRaises(MihomoError):
            await c.outbound_connect(second.id)
        for invalid in ([first, first], [remote()]):
            if len(invalid) == 1:
                invalid[0].id = "main"
            with self.assertRaises(ValueError):
                await c.outbound_register(invalid)
        await c.outbound_delete_all()
        await c.outbound_delete_all()
        proxies = (await c.rest_client.get_proxies())["proxies"]
        self.assertNotIn(first.id, proxies)
        for role in ("main", "test"):
            self.assertEqual(proxies[role]["all"], ["REJECT"])
            self.assertEqual(proxies[role]["now"], "REJECT")
        assert c.test_port is not None
        await c._check_listener(c.test_port)

    async def test_commands_do_not_read_configuration(self):
        c = self.client
        await c.service_start()
        request = c.rest_client.request

        async def command_only(method, path, body=None):
            self.assertNotEqual(method, "GET")
            return await request(method, path, body)

        with patch.object(c.rest_client, "request", side_effect=command_only):
            first, second = remote(), remote()
            await c.outbound_register([first, second])
            await c.outbound_connect(first.id)
            await c.test_connect(second.id)
            await c.test_stop()
            await c.inbound_set(inbound())
            await c.routing_set(
                [RoutingRule(priority=1, reg="*.example.com", action=RoutingAction.BLOCK)]
            )
            await c.outbound_delete_all()
        self.assertFalse(hasattr(c.process_manager, "config"))

    async def asyncSetUp(self):
        self.client = MihomoClient()
        self.listeners = []
        self.writers = []
        self.datagrams = []

    async def asyncTearDown(self):
        for transport in self.datagrams:
            transport.close()
        for writer in self.writers:
            writer.close()
        await self.client.service_stop()
        for listener in self.listeners:
            listener.close()
            await listener.wait_closed()

    async def echo_vless(self, label):
        async def handle(reader, writer):
            self.writers.append(writer)
            try:
                header = await reader.readexactly(18)
                self.assertEqual(header[1:17], UUID(int=1).bytes)
                await reader.readexactly(header[17])
                command = await reader.readexactly(4)  # command, port, address type
                size = {1: 4, 3: 16}.get(command[3])
                if size is None:
                    size = (await reader.readexactly(1))[0]
                await reader.readexactly(size)
                writer.write(b"\x00\x00")
                await writer.drain()
                while data := await reader.read(1024):
                    writer.write(label + data)
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()

        listener = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.listeners.append(listener)
        return remote(listener.sockets[0].getsockname()[1])

    async def socks(self, port, auth=None):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        self.writers.append(writer)
        method = b"\x02" if auth else b"\x00"
        writer.write(b"\x05\x01" + method)
        await writer.drain()
        self.assertEqual(await reader.readexactly(2), b"\x05" + method)
        if auth:
            user, password = auth
            writer.write(bytes([1, len(user)]) + user + bytes([len(password)]) + password)
            await writer.drain()
            self.assertEqual(await reader.readexactly(2), b"\x01\x00")
        # Documentation address; fake local VLESS endpoint does not dial it.
        writer.write(b"\x05\x01\x00\x01\xc0\x00\x02\x01\x00\x50")
        await writer.drain()
        reply = await reader.readexactly(4)
        self.assertEqual(reply[:2], b"\x05\x00")
        await reader.readexactly(6 if reply[3] == 1 else 18)
        return reader, writer

    async def echo(self, label):
        """A plain TCP echo server on 127.0.0.1 that DIRECT traffic reaches; returns its port."""

        async def handle(reader, writer):
            self.writers.append(writer)
            try:
                while data := await reader.read(1024):
                    writer.write(label + data)
                    await writer.drain()
            except ConnectionError:
                pass
            finally:
                writer.close()

        listener = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.listeners.append(listener)
        return listener.sockets[0].getsockname()[1]

    async def socks_to(self, port, host, destination_port):
        """A SOCKS5 connection to a domain or an IPv4 address; Mihomo routes it after the reply."""
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        self.writers.append(writer)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        self.assertEqual(await reader.readexactly(2), b"\x05\x00")
        try:
            address = b"\x01" + socket.inet_aton(host)
        except OSError:
            address = b"\x03" + bytes([len(host)]) + host.encode()
        writer.write(b"\x05\x01\x00" + address + destination_port.to_bytes(2, "big"))
        await writer.drain()
        reply = await reader.readexactly(4)
        self.assertEqual(reply[:2], b"\x05\x00")
        await reader.readexactly(6 if reply[3] == 1 else 18)
        return reader, writer

    async def blocked(self, connection):
        reader, writer = connection
        try:
            writer.write(b"ping")
            await writer.drain()
            async with asyncio.timeout(5):
                self.assertEqual(await reader.read(1024), b"")
        except ConnectionResetError:
            pass

    async def ping(self, connection, label):
        reader, writer = connection
        writer.write(b"ping")
        await writer.drain()
        async with asyncio.timeout(5):
            self.assertEqual(await reader.readexactly(len(label) + 4), label + b"ping")

    async def test_main_and_test_traffic_and_live_connection(self):
        c = self.client
        self.assertIsInstance(c, CoreClient)
        self.assertIsInstance(c.process_manager, CoreProcessManagerInterface)
        first, second = await self.echo_vless(b"main:"), await self.echo_vless(b"test:")
        await c.service_start()
        main = inbound()
        await c.inbound_set(main)
        await c.outbound_register([first, second])
        await c.outbound_connect(first.id)
        pid = c.process_manager.status().pid
        connection = await self.socks(main.proxy_port)
        await self.ping(connection, b"main:")
        await c.test_connect(second.id)
        await self.ping(await self.socks(c.test_port), b"test:")
        await self.ping(connection, b"main:")
        await c.test_connect(first.id)
        await self.ping(await self.socks(c.test_port), b"main:")
        await self.ping(connection, b"main:")
        await c.outbound_connect(second.id)
        await self.ping(await self.socks(main.proxy_port), b"test:")
        await self.ping(await self.socks(c.test_port), b"main:")
        await c.test_stop()
        await c.test_stop()
        proxies = (await c.rest_client.get_proxies())["proxies"]
        self.assertEqual(proxies["main"]["now"], second.id)
        self.assertEqual(proxies["test"]["now"], "REJECT")
        assert c.test_port is not None
        await c._check_listener(c.test_port)
        await c.test_connect(first.id)
        await self.ping(await self.socks(c.test_port), b"main:")
        self.assertEqual(c.process_manager.status().pid, pid)
        await self.ping(connection, b"main:")
        await c.outbound_disconnect()
        proxies = (await c.rest_client.get_proxies())["proxies"]
        self.assertEqual((proxies["main"]["now"], proxies["test"]["now"]), ("REJECT", first.id))
        await self.ping(await self.socks(c.test_port), b"main:")
        await c.outbound_connect(second.id)
        await self.ping(await self.socks(main.proxy_port), b"test:")

    async def test_inbounds_keep_routes_and_connections(self):
        c = self.client
        first, second = await self.echo_vless(b"main:"), await self.echo_vless(b"test:")
        await c.service_start()
        main = inbound()
        await c.inbound_set(main)
        await c.outbound_register([first, second])
        await c.outbound_connect(first.id)
        await c.test_connect(second.id)
        connection = await self.socks(main.proxy_port)
        await self.ping(connection, b"main:")
        # A new inbound replaces the config: routes and open connections stay.
        other = inbound(proxy_username="user", proxy_password="secret")
        await c.inbound_set(other)
        proxies = (await c.rest_client.get_proxies())["proxies"]
        self.assertEqual((proxies["main"]["now"], proxies["test"]["now"]), (first.id, second.id))
        await self.ping(connection, b"main:")
        await self.ping(await self.socks(c.test_port), b"test:")
        await self.ping(await self.socks(other.proxy_port, (b"user", b"secret")), b"main:")
        # The same listener again sends no config.
        with patch.object(c.rest_client, "replace_config") as replaced:
            await c.inbound_set(replace(main, error="ignored"))
        replaced.assert_not_called()
        moved = replace(main, proxy_port=free_port())
        await c.inbound_set(moved)
        await self.ping(await self.socks(moved.proxy_port), b"main:")
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", main.proxy_port)
        # New servers block the routes but keep the inbounds.
        await c.outbound_register([first])
        self.assertEqual((await c.rest_client.get_proxies())["proxies"]["main"]["now"], "REJECT")
        await c.outbound_connect(first.id)
        await self.ping(await self.socks(moved.proxy_port), b"main:")
        await c.inbound_delete(moved.id)
        await c.inbound_delete(moved.id)
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", moved.proxy_port)
        await self.ping(await self.socks(other.proxy_port, (b"user", b"secret")), b"main:")

    async def test_inbound_failures_keep_the_previous_listener(self):
        c = self.client
        with self.assertRaises(RuntimeError):
            await c.inbound_set(inbound())
        await c.service_start()
        first = remote()
        await c.outbound_register([first])
        await c.outbound_connect(first.id)
        listener = inbound()
        await c.inbound_set(listener)
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            with self.assertRaises(InboundError) as raised:
                await c.inbound_set(replace(listener, proxy_port=occupied.getsockname()[1]))
            self.assertEqual(raised.exception.field, "proxy_port")
        # 192.0.2.0/24 is reserved for documentation and never assigned.
        with self.assertRaises(InboundError) as raised:
            await c.inbound_set(replace(listener, proxy_listen="192.0.2.1"))
        self.assertEqual(raised.exception.field, "proxy_listen")
        with self.assertRaises(InboundError):
            await c.inbound_set(inbound(proxy_port=c.test_port))
        # Mihomo accepts a listener it cannot open; the previous config comes back.
        failed = InboundError("The core could not listen", "proxy_port")
        new = inbound()
        with patch.object(c, "_check_inbound_listening", side_effect=failed):
            with self.assertRaises(InboundError):
                await c.inbound_set(replace(listener, proxy_port=free_port()))
            with self.assertRaises(InboundError):
                await c.inbound_set(new)
        await c._check_inbound_listening(listener)
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", new.proxy_port)
        self.assertEqual((await c.rest_client.get_proxies())["proxies"]["main"]["now"], first.id)
        with self.assertRaises(ValueError):
            await c.inbound_set(replace(listener, id="test"))

    async def test_udp_routes_are_independent(self):
        loop = asyncio.get_running_loop()

        async def endpoint(label):
            class Echo(asyncio.DatagramProtocol):
                def connection_made(self, transport):
                    self.transport = transport

                def datagram_received(self, data, addr):
                    # Plain Shadowsocks UDP: IPv4 destination header followed by payload.
                    self.transport.sendto(data[:7] + label + data[7:], addr)

            transport, _ = await loop.create_datagram_endpoint(Echo, local_addr=("127.0.0.1", 0))
            self.datagrams.append(transport)
            return OutboundServer(
                name="udp",
                address="127.0.0.1",
                port=transport.get_extra_info("sockname")[1],
                protocol=OutboundProtocol.SHADOWSOCKS,
                shadowsocks_password="",
                shadowsocks_method=ShadowsocksMethod.NONE,
            )

        c = self.client
        first, second = await endpoint(b"main:"), await endpoint(b"test:")
        await c.service_start()
        main = inbound()
        await c.inbound_set(main)
        await c.outbound_register([first, second])
        await c.outbound_connect(first.id)
        await c.test_connect(second.id)
        for port, label in ((main.proxy_port, b"main:"), (c.test_port, b"test:")):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            self.writers.append(writer)
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            self.assertEqual(await reader.readexactly(2), b"\x05\x00")
            writer.write(b"\x05\x03\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()
            self.assertEqual((await reader.readexactly(10))[:2], b"\x05\x00")
            with socket.socket(type=socket.SOCK_DGRAM) as udp:
                udp.setblocking(False)
                payload = b"\x00\x00\x00\x01\xc0\x00\x02\x01\x00\x50ping"
                await loop.sock_sendto(udp, payload, ("127.0.0.1", port))
                async with asyncio.timeout(5):
                    response = await loop.sock_recv(udp, 1024)
                self.assertEqual(response[10:], label + b"ping")

    async def test_test_port_is_free_and_not_reserved(self):
        c = self.client
        reserved = free_port()
        with socket.socket(type=socket.SOCK_DGRAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            taken = occupied.getsockname()[1]
            offers = iter([reserved, taken])
            bind = socket.socket.bind

            def offer(sock, address):
                # The OS offers the reserved port, then the one taken for UDP, then free ones.
                if sock.type == socket.SOCK_STREAM and address[1] == 0:
                    address = (address[0], next(offers, 0))
                bind(sock, address)

            with patch.object(socket.socket, "bind", offer):
                self.assertNotIn(c._free_port({reserved}), {reserved, taken})
            self.assertEqual(list(offers), [])
        with self.assertRaises(MihomoError):
            c._free_port(range(65536))

        await c.service_start({reserved})
        assert c.test_port is not None
        self.assertNotIn(c.test_port, {reserved, c.process_manager.api_port})
        await c._check_listener(c.test_port)
        await c.service_stop()
        self.assertIsNone(c.test_port)
        failure = MihomoError("No free port")
        with (
            patch.object(MihomoClient, "_free_port", side_effect=failure),
            self.assertRaises(MihomoError),
        ):
            await c.service_start()
        self.assertEqual(c.process_manager.status().state, CoreState.STOPPED)

    async def test_blocked_start_and_rejected_config(self):
        c = self.client
        with self.assertRaises(RuntimeError):
            await c.test_connect(remote().id)
        await c.service_start()
        first = remote()
        await c.outbound_register([first])
        await c.outbound_connect(first.id)
        model = remote()
        model.vless_encryption = "invalid"
        with self.assertRaises(MihomoError):
            await c.outbound_register([model])
        self.assertEqual((await c.rest_client.get_proxies())["proxies"]["main"]["now"], first.id)
        await c.service_stop()
        self.assertEqual(c.process_manager.status().state, CoreState.STOPPED)
        await c.service_start()
        self.assertEqual((await c.rest_client.get_proxies())["proxies"]["main"]["now"], "REJECT")

    async def test_core_accepts_supported_protocols(self):
        c = self.client
        await c.service_start()
        cases = [
            remote(),
            OutboundServer(
                name="ss",
                address="127.0.0.1",
                port=12345,
                protocol=OutboundProtocol.SHADOWSOCKS,
                shadowsocks_password="sample",
                shadowsocks_method=ShadowsocksMethod.AES_128_GCM,
            ),
            OutboundServer(
                name="hy2",
                address="127.0.0.1",
                port=12345,
                protocol=OutboundProtocol.HYSTERIA,
                hysteria_auth="sample",
                transport=OutboundTransport.HYSTERIA,
                security=OutboundSecurity.TLS,
            ),
        ]
        for transport in (OutboundTransport.WS, OutboundTransport.GRPC, OutboundTransport.XHTTP):
            model = remote()
            model.transport = transport
            model.security = OutboundSecurity.TLS
            model.server_name = "example.com"
            cases.append(model)
        model = remote()
        model.security = OutboundSecurity.REALITY
        model.public_key = "a" * 42 + "E"
        model.fingerprint = "chrome"
        model.server_name = "example.com"
        cases.append(model)
        for model in cases:
            with self.subTest(protocol=model.protocol, transport=model.transport):
                await c.outbound_register([model])
                await c.outbound_connect(model.id)
                self.assertIn(model.id, (await c.rest_client.get_proxies())["proxies"])

    async def test_process_failure_and_api_auth(self):
        c = self.client
        await c.service_start()
        from server.cores.mihomo.mihomo_rest_client import MihomoRestClient

        with self.assertRaises(MihomoError):
            await asyncio.to_thread(
                MihomoRestClient._request,
                c.process_manager.api_port,
                "incorrect",
                "GET",
                "/version",
                None,
            )
        process, task = c.process_manager._process, c.process_manager._task
        assert process is not None and task is not None
        process.kill()
        await task
        self.assertEqual(c.process_manager.status().state, CoreState.FAILED)
        self.assertIsNone(c.process_manager.status().pid)

    async def test_routing_rules(self):
        c = self.client
        server = await self.echo_vless(b"main:")
        direct = await self.echo(b"direct:")
        with self.assertRaises(RuntimeError):
            await c.routing_set([])
        await c.service_start()
        listener = inbound()
        await c.inbound_set(listener)
        await c.outbound_register([server])
        await c.outbound_connect(server.id)
        await c.test_connect(server.id)
        port, test_port = listener.proxy_port, c.test_port
        # The fake server does not dial: whatever it answers went through the server.
        await self.ping(await self.socks_to(port, "localhost", direct), b"main:")

        def rule(priority, reg, action):
            return RoutingRule(priority=priority, reg=reg, action=RoutingAction(action))

        rules = [
            rule(3, "*.example.com", "block"),
            rule(1, "LocalHost", "direct"),
            rule(2, "127.0.0.*", "direct"),
            rule(4, "10.*", "block"),
        ]
        await c.routing_set(rules)
        self.assertEqual(c._rules, sorted(rules, key=lambda item: item.priority))
        open_direct = await self.socks_to(port, "localhost", direct)
        await self.ping(open_direct, b"direct:")
        await self.ping(await self.socks_to(port, "127.0.0.1", direct), b"direct:")
        await self.blocked(await self.socks_to(port, "www.example.com", 80))
        await self.blocked(await self.socks_to(port, "10.1.2.3", 80))
        # Not a subdomain, so no rule matches and the traffic goes through the server.
        await self.ping(await self.socks_to(port, "example.com", 80), b"main:")
        # The test endpoint ignores the rules.
        await self.ping(await self.socks_to(test_port, "localhost", direct), b"main:")
        await self.ping(await self.socks_to(test_port, "www.example.com", 80), b"main:")

        # The first matching rule wins; open connections keep their way.
        await c.routing_set([rule(1, "*", "block"), *rules])
        await self.blocked(await self.socks_to(port, "localhost", direct))
        await self.blocked(await self.socks_to(port, "example.com", 80))
        await self.ping(open_direct, b"direct:")
        await self.ping(await self.socks_to(test_port, "localhost", direct), b"main:")

        # proxy follows the main route; direct works while nothing is connected.
        await c.routing_set([rule(1, "example.com", "proxy"), rule(2, "localhost", "direct")])
        await self.ping(await self.socks_to(port, "example.com", 80), b"main:")
        await c.outbound_disconnect()
        await self.blocked(await self.socks_to(port, "example.com", 80))
        await self.ping(await self.socks_to(port, "localhost", direct), b"direct:")
        # New servers and inbounds keep the rules.
        await c.outbound_register([server])
        other = inbound()
        await c.inbound_set(other)
        await self.ping(await self.socks_to(other.proxy_port, "localhost", direct), b"direct:")
        await self.blocked(await self.socks_to(other.proxy_port, "example.com", 80))
        rule_types = [item["type"] for item in (await c.rest_client.get_rules())["rules"]]
        self.assertEqual(
            rule_types, ["InName", "DomainRegex", "DomainRegex", "InName", "InName", "Match"]
        )
        await c.routing_set([])
        await self.blocked(await self.socks_to(port, "localhost", direct))
