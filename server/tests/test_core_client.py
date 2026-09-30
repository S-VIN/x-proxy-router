import asyncio
import socket
import unittest
from copy import deepcopy
from dataclasses import replace
from typing import Any
from unittest.mock import patch
from uuid import UUID

import grpc

from server.cores import CoreClient, InboundError
from server.cores.xray.grpc_generated.app.router.command.command_pb2 import RoutingContext
from server.cores.xray.outbound_protobuf import build_outbound
from server.cores.xray.xray_client import XrayClient, inbound_tag
from server.models import (
    CoreState,
    InboundServer,
    InboundType,
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
    return OutboundServer(
        name="local",
        address="127.0.0.1",
        port=23456,
        protocol=OutboundProtocol.VLESS,
        vless_uuid=UUID(int=1),
    )


def inbound(**values: Any) -> InboundServer:
    values.setdefault("proxy_port", free_port())
    return InboundServer(type=InboundType.PROXY, **values)


class CoreClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_and_delete_servers(self):
        c = self.client
        await c.service_start(free_port())
        listener = inbound()
        await c.inbound_set(listener)
        first, second = server(), server()
        await c.outbound_register([first, second])
        first.port += 1
        await c.outbound_register([first])
        tags = [item.tag for item in await c.grpc_client.list_outbounds()]
        self.assertEqual(tags.count(first.id), 1)
        self.assertNotIn(second.id, tags)
        self.assertEqual(await self.route(listener), "blocked")
        with self.assertRaises(ValueError):
            await c.outbound_register([first, first])
        await c.outbound_connect(first.id)
        await c.outbound_delete_all()
        await c.outbound_delete_all()
        self.assertEqual([item.tag for item in await c.grpc_client.list_outbounds()], ["blocked"])
        self.assertEqual(await self.route(listener), "blocked")
        # Servers come and go; the inbound stays.
        await self.handshake(listener.proxy_port)

    async def asyncSetUp(self):
        self.client = XrayClient()

    async def asyncTearDown(self):
        await self.client.service_stop()

    async def route(self, listener=None):
        """The outbound of traffic from an inbound, or from the test endpoint."""
        tag = inbound_tag(listener.id) if listener is not None else self.client._test_inbound
        response = await self.client.grpc_client.test_route(
            RoutingContext(InboundTag=tag, TargetDomain="example.com")
        )
        return response.OutboundTag

    async def handshake(self, port, method=b"\x00"):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(b"\x05\x01" + method)
            await writer.drain()
            async with asyncio.timeout(5):
                self.assertEqual(await reader.readexactly(2), b"\x05" + method)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_independent_routes_and_replacement(self):
        c = self.client
        self.assertIsInstance(c, CoreClient)
        await c.service_start(free_port())
        main, other = inbound(), inbound()
        await c.inbound_set(main)
        await self.handshake(main.proxy_port)
        self.assertEqual(await self.route(main), "blocked")
        first, second = server(), server()
        await c.outbound_register([first, second])
        await c.outbound_connect(first.id)
        invalid = server()
        invalid.vless_encryption = "invalid"
        with self.assertRaises(ValueError):
            await c.outbound_register([invalid])
        self.assertEqual(await self.route(main), first.id)
        self.assertEqual(await self.route(), "blocked")
        await c.test_connect(second.id)
        # Every inbound takes the main route; a new one does not change the routes.
        await c.inbound_set(other)
        self.assertEqual(await self.route(other), first.id)
        self.assertEqual(await self.route(), second.id)
        await c.outbound_connect(second.id)
        self.assertEqual(await self.route(main), second.id)
        self.assertEqual(await self.route(other), second.id)
        self.assertEqual(await self.route(), second.id)
        await c.test_connect(first.id)
        self.assertEqual(await self.route(main), second.id)
        await c.test_stop()
        await c.test_stop()
        await c.test_connect(first.id)
        await c.outbound_disconnect()
        self.assertEqual(await self.route(main), "blocked")
        self.assertEqual(await self.route(), first.id)
        await c.outbound_connect(second.id)
        self.assertEqual(await self.route(main), second.id)
        await c.test_stop()
        self.assertEqual(len(await c.grpc_client.list_inbounds()), 3)
        self.assertEqual(len(await c.grpc_client.list_outbounds()), 3)
        await c.outbound_register([first])
        self.assertEqual(await self.route(main), "blocked")
        with self.assertRaises(ValueError):
            await c.outbound_connect(second.id)
        await c.service_stop()
        self.assertEqual(c.process_manager.status().state, CoreState.STOPPED)
        await c.service_start(free_port())
        self.assertEqual(await self.route(), "blocked")
        self.assertEqual(len(await c.grpc_client.list_inbounds()), 1)

    async def test_inbound_replacement_authentication_and_deletion(self):
        c = self.client
        await c.service_start(free_port())
        first = server()
        await c.outbound_register([first])
        await c.outbound_connect(first.id)
        listener = inbound()
        await c.inbound_set(listener)
        # The same listener again changes nothing.
        await c.inbound_set(replace(listener, error="ignored"))
        secured = replace(listener, proxy_username="user", proxy_password="secret")
        await c.inbound_set(secured)
        await self.handshake(listener.proxy_port, b"\x02")
        moved = replace(secured, proxy_listen="0.0.0.0", proxy_port=free_port())
        await c.inbound_set(moved)
        await self.handshake(moved.proxy_port, b"\x02")
        with self.assertRaises(OSError):
            await self.handshake(listener.proxy_port)
        self.assertEqual(await self.route(moved), first.id)
        await c.inbound_delete(moved.id)
        await c.inbound_delete(moved.id)
        with self.assertRaises(OSError):
            await self.handshake(moved.proxy_port)
        self.assertEqual(len(await c.grpc_client.list_inbounds()), 1)
        self.assertEqual([rule.ruleTag for rule in await c.grpc_client.list_rules()], ["test"])

    async def test_inbound_failures_keep_the_previous_listener(self):
        c = self.client
        with self.assertRaises(RuntimeError):
            await c.inbound_set(inbound())
        await c.service_start(free_port())
        listener = inbound()
        await c.inbound_set(listener)
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            busy = replace(listener, proxy_port=occupied.getsockname()[1])
            with self.assertRaises(InboundError) as raised:
                await c.inbound_set(busy)
            self.assertEqual(raised.exception.field, "proxy_port")
        # 192.0.2.0/24 is reserved for documentation and never assigned.
        with self.assertRaises(InboundError) as raised:
            await c.inbound_set(replace(listener, proxy_listen="192.0.2.1"))
        self.assertEqual(raised.exception.field, "proxy_listen")
        with self.assertRaises(InboundError):
            await c.inbound_set(replace(listener, proxy_port=c.test_port))
        # The core accepted the change but does not answer: the old listener comes back.
        failed = InboundError("The core could not listen", "proxy_port")
        with patch.object(c, "_check_inbound_listening", side_effect=failed):
            with self.assertRaises(InboundError):
                await c.inbound_set(replace(listener, proxy_username="u", proxy_password="p"))
            with self.assertRaises(InboundError):
                await c.inbound_set(inbound())
        await self.handshake(listener.proxy_port)
        self.assertEqual(len(await c.grpc_client.list_inbounds()), 2)
        with self.assertRaises(ValueError):
            await c.inbound_set(replace(listener, id="test"))

    async def test_port_failures_preserve_existing_listener(self):
        c = self.client
        with self.assertRaises(RuntimeError):
            await c.test_connect(server().id)
        with self.assertRaises(ValueError):
            await c.service_start(0)
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            # Xray cannot listen on the port and rejects the inbound over gRPC.
            with self.assertRaises(grpc.RpcError):
                await c.service_start(occupied.getsockname()[1])
        self.assertEqual(c.process_manager.status().state, CoreState.STOPPED)
        await c.service_start(free_port())
        await self.handshake(c.test_port)

    async def test_compile_protocols_and_preserve_model(self):
        cases = [
            server(),
            OutboundServer(
                name="ss",
                address="127.0.0.1",
                port=1234,
                protocol=OutboundProtocol.SHADOWSOCKS,
                shadowsocks_password="test",
                shadowsocks_method=ShadowsocksMethod.AES_128_GCM,
            ),
            OutboundServer(
                name="hy",
                address="127.0.0.1",
                port=1234,
                protocol=OutboundProtocol.HYSTERIA,
                hysteria_auth="test",
                transport=OutboundTransport.HYSTERIA,
                security=OutboundSecurity.TLS,
                server_name="example.com",
            ),
        ]
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
