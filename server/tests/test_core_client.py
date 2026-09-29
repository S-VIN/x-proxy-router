import asyncio
import socket
import unittest
from copy import deepcopy
from uuid import UUID

from server.cores import CoreClient
from server.cores.xray.grpc_generated.app.router.command.command_pb2 import RoutingContext
from server.cores.xray.outbound_protobuf import build_outbound
from server.cores.xray.xray_client import XrayClient
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


def server():
    return OutboundServer(name="local", address="127.0.0.1", port=23456,
                          protocol=OutboundProtocol.VLESS, vless_uuid=UUID(int=1))


class CoreClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_and_delete_servers(self):
        c = self.client
        await c.service_start(free_port(), free_port())
        first, second = server(), server()
        await c.outbound_register([first, second])
        first.port += 1
        await c.outbound_register([first])
        tags = [item.tag for item in await c.grpc_client.list_outbounds()]
        self.assertEqual(tags.count(first.id), 1)
        self.assertNotIn(second.id, tags)
        self.assertEqual(await self.route("main"), "blocked")
        with self.assertRaises(ValueError):
            await c.outbound_register([first, first])
        await c.outbound_connect(first.id)
        await c.outbound_delete_all()
        await c.outbound_delete_all()
        self.assertEqual([item.tag for item in await c.grpc_client.list_outbounds()], ["blocked"])
        self.assertEqual(await self.route("main"), "blocked")
        await self.handshake(c.proxy_port)

    async def asyncSetUp(self):
        self.client = XrayClient()

    async def asyncTearDown(self):
        await self.client.service_stop()

    async def route(self, role):
        response = await self.client.grpc_client.test_route(RoutingContext(
            InboundTag=self.client._inbounds[role], TargetDomain="example.com"))
        return response.OutboundTag

    async def handshake(self, port):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            async with asyncio.timeout(5):
                self.assertEqual(await reader.readexactly(2), b"\x05\x00")
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_independent_routes_and_replacement(self):
        c = self.client
        self.assertIsInstance(c, CoreClient)
        await c.service_start(free_port(), free_port())
        await self.handshake(c.proxy_port)
        self.assertEqual(await self.route("main"), "blocked")
        first, second = server(), server()
        await c.outbound_register([first, second])
        await c.outbound_connect(first.id)
        invalid = server()
        invalid.vless_encryption = "invalid"
        with self.assertRaises(Exception):
            await c.outbound_register([invalid])
        self.assertEqual(await self.route("main"), first.id)
        self.assertEqual(await self.route("test"), "blocked")
        await c.test_connect(second.id)
        await c.outbound_connect(second.id)
        self.assertEqual(await self.route("main"), second.id)
        self.assertEqual(await self.route("test"), second.id)
        await c.test_connect(first.id)
        self.assertEqual(await self.route("main"), second.id)
        await c.test_stop()
        await c.test_stop()
        await c.test_connect(first.id)
        await c.outbound_disconnect()
        self.assertEqual(await self.route("main"), "blocked")
        self.assertEqual(await self.route("test"), first.id)
        await c.outbound_connect(second.id)
        self.assertEqual(await self.route("main"), second.id)
        await c.test_stop()
        self.assertEqual(len(await c.grpc_client.list_inbounds()), 2)
        self.assertEqual(len(await c.grpc_client.list_outbounds()), 3)
        await c.outbound_register([first])
        self.assertEqual(await self.route("main"), "blocked")
        with self.assertRaises(ValueError):
            await c.outbound_connect(second.id)
        await c.service_stop()
        self.assertEqual(c.process_manager.status().state, CoreState.STOPPED)
        await c.service_start(free_port(), free_port())
        self.assertEqual(await self.route("main"), "blocked")

    async def test_port_failures_preserve_existing_listener(self):
        c = self.client
        with self.assertRaises(RuntimeError):
            await c.test_connect(server().id)
        with self.assertRaises(ValueError):
            await c.service_start(0, free_port())
        port = free_port()
        with self.assertRaises(ValueError):
            await c.service_start(port, port)
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            with self.assertRaises(Exception):
                await c.service_start(free_port(), occupied.getsockname()[1])
        self.assertEqual(c.process_manager.status().state, CoreState.STOPPED)
        await c.service_start(free_port(), free_port())
        await self.handshake(c.proxy_port)
        await self.handshake(c.test_port)

    async def test_compile_protocols_and_preserve_model(self):
        cases = [server(), OutboundServer(name="ss", address="127.0.0.1", port=1234,
                 protocol=OutboundProtocol.SHADOWSOCKS, shadowsocks_password="test",
                 shadowsocks_method=ShadowsocksMethod.AES_128_GCM),
                 OutboundServer(name="hy", address="127.0.0.1", port=1234,
                 protocol=OutboundProtocol.HYSTERIA, hysteria_auth="test",
                 transport=OutboundTransport.HYSTERIA,
                 security=OutboundSecurity.TLS, server_name="example.com")]
        for transport in (OutboundTransport.WS, OutboundTransport.GRPC, OutboundTransport.XHTTP):
            remote = server()
            remote.transport = transport
            remote.security = OutboundSecurity.TLS
            remote.server_name = "example.com"
            cases.append(remote)
        for remote in cases:
            before = deepcopy(remote)
            XrayClient().check_outbound_server_config(remote)  # No running core needed.
            config = build_outbound(remote, "test")
            self.assertEqual(config.tag, "test")
            self.assertTrue(config.proxy_settings.value)
            self.assertEqual(remote, before)
        unsupported = server()
        unsupported.vless_encryption = "unknown"
        with self.assertRaisesRegex(ValueError, "Unsupported VLESS encryption"):
            XrayClient().check_outbound_server_config(unsupported)
