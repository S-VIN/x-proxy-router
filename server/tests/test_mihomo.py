import asyncio
import socket
import unittest
from copy import deepcopy
from uuid import UUID

from server.cores import CoreClient, CoreProcessManagerInterface
from server.cores.mihomo.mihomo_client import MihomoClient
from server.cores.mihomo.mihomo_process_manager import MihomoError
from server.cores.mihomo.outbound_config import outbound_config
from server.models import (
    CoreState,
    OutboundProtocol,
    OutboundSecurity,
    OutboundServer,
    OutboundTransport,
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


class MihomoIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_and_delete_servers(self):
        c = self.client
        await c.service_start(free_port(), free_port())
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
        assert c.proxy_port is not None and c.test_port is not None
        await c._check_listener(c.proxy_port)
        await c._check_listener(c.test_port)

    async def test_commands_do_not_read_or_cache_configuration(self):
        from unittest.mock import patch

        c = self.client
        await c.service_start(free_port(), free_port())
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
            await c.outbound_delete_all()
        self.assertEqual(
            set(vars(c)), {"process_manager", "rest_client", "proxy_port", "test_port"}
        )
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

    async def socks(self, port):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        self.writers.append(writer)
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        self.assertEqual(await reader.readexactly(2), b"\x05\x00")
        # Documentation address; fake local VLESS endpoint does not dial it.
        writer.write(b"\x05\x01\x00\x01\xc0\x00\x02\x01\x00\x50")
        await writer.drain()
        reply = await reader.readexactly(4)
        self.assertEqual(reply[:2], b"\x05\x00")
        await reader.readexactly(6 if reply[3] == 1 else 18)
        return reader, writer

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
        await c.service_start(free_port(), free_port())
        await c.outbound_register([first, second])
        await c.outbound_connect(first.id)
        pid = c.process_manager.status().pid
        connection = await self.socks(c.proxy_port)
        await self.ping(connection, b"main:")
        await c.test_connect(second.id)
        await self.ping(await self.socks(c.test_port), b"test:")
        await self.ping(connection, b"main:")
        await c.test_connect(first.id)
        await self.ping(await self.socks(c.test_port), b"main:")
        await self.ping(connection, b"main:")
        await c.outbound_connect(second.id)
        await self.ping(await self.socks(c.proxy_port), b"test:")
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
        await self.ping(await self.socks(c.proxy_port), b"test:")

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
        await c.service_start(free_port(), free_port())
        await c.outbound_register([first, second])
        await c.outbound_connect(first.id)
        await c.test_connect(second.id)
        for port, label in ((c.proxy_port, b"main:"), (c.test_port, b"test:")):
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

    async def test_blocked_start_invalid_ports_and_rejected_config(self):
        c = self.client
        with self.assertRaises(ValueError):
            await c.service_start(False, free_port())
        port = free_port()
        with self.assertRaises(ValueError):
            await c.service_start(port, port)
        with self.assertRaises(RuntimeError):
            await c.test_connect(remote().id)
        for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            with socket.socket(type=kind) as occupied:
                occupied.bind(("127.0.0.1", 0))
                with self.assertRaises(OSError):
                    await c.service_start(free_port(), occupied.getsockname()[1])
        await c.service_start(free_port(), free_port())
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
        await c.service_start(free_port(), free_port())
        self.assertEqual((await c.rest_client.get_proxies())["proxies"]["main"]["now"], "REJECT")

    async def test_core_accepts_supported_protocols(self):
        c = self.client
        await c.service_start(free_port(), free_port())
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
        await c.service_start(free_port(), free_port())
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
