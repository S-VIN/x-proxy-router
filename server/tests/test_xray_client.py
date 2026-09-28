import asyncio
import socket
import unittest

import grpc

from server import XrayProcessManager
from server.cores.xray.grpc_generated.app.proxyman.config_pb2 import ReceiverConfig
from server.cores.xray.grpc_generated.app.router.command.command_pb2 import RoutingContext
from server.cores.xray.grpc_generated.app.router.config_pb2 import RoutingRule
from server.cores.xray.grpc_generated.common.net.address_pb2 import IPOrDomain
from server.cores.xray.grpc_generated.common.net.port_pb2 import PortList, PortRange
from server.cores.xray.grpc_generated.core.config_pb2 import (
    InboundHandlerConfig,
    OutboundHandlerConfig,
)
from server.cores.xray.grpc_generated.proxy.freedom.config_pb2 import Config as FreedomConfig
from server.cores.xray.grpc_generated.proxy.socks.config_pb2 import ServerConfig
from server.cores.xray.xray_grpc_client import XrayGrpcClient, typed_message
from server.models import CoreState


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = XrayProcessManager()
        self.client = XrayGrpcClient()

    async def asyncTearDown(self):
        await self.client.close()
        await self.manager.stop()

    async def test_handlers_and_routing(self):
        await self.manager.start()
        await self.client.connect(self.manager.api_port)
        client = self.client
        self.assertEqual([item.tag for item in await client.list_outbounds()], ["blocked"])
        await client.add_outbound(OutboundHandlerConfig(
            tag="direct", proxy_settings=typed_message(FreedomConfig())))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        await client.add_inbound(InboundHandlerConfig(
            tag="socks", proxy_settings=typed_message(ServerConfig()),
            receiver_settings=typed_message(ReceiverConfig(
                listen=IPOrDomain(ip=socket.inet_aton("127.0.0.1")),
                port_list=PortList(range=[PortRange(From=port, To=port)])))))
        self.assertIn("socks", [item.tag for item in await client.list_inbounds()])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(b"\x05\x01\x00")
            await writer.drain()
            async with asyncio.timeout(5):
                self.assertEqual(await reader.readexactly(2), b"\x05\x00")
        finally:
            writer.close()
            await writer.wait_closed()

        await client.replace_rules([RoutingRule(rule_tag="selected", inbound_tag=["socks"], tag="direct")])
        route = await client.test_route(RoutingContext(InboundTag="socks", TargetDomain="example.com"))
        self.assertEqual(route.OutboundTag, "direct")
        await client.replace_rules([RoutingRule(rule_tag="selected", inbound_tag=["socks"], tag="blocked")])
        route = await client.test_route(RoutingContext(InboundTag="socks", TargetDomain="example.com"))
        self.assertEqual(route.OutboundTag, "blocked")
        await client.append_rules([RoutingRule(rule_tag="extra", inbound_tag=["other"], tag="direct")])
        self.assertEqual([rule.ruleTag for rule in await client.list_rules()], ["selected", "extra"])
        await client.remove_rule("extra")
        await client.replace_rules([])
        self.assertEqual(await client.list_rules(), [])
        await client.remove_inbound("socks")
        await client.remove_outbound("direct")
        self.assertEqual(await client.list_inbounds(), [])
        self.assertEqual([item.tag for item in await client.list_outbounds()], ["blocked"])
        with self.assertRaises(grpc.aio.AioRpcError):
            await client.test_route(RoutingContext(InboundTag="missing"))
        self.assertEqual(self.manager.status().state, CoreState.RUNNING)

    async def test_client_connection_timeout_and_closed_usage(self):
        client = XrayGrpcClient()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            with self.assertRaises(TimeoutError):
                await client.connect(listener.getsockname()[1])
        with self.assertRaises(RuntimeError):
            await client.list_outbounds()
        await client.close()

    async def test_client_works_after_process_restart(self):
        await self.manager.start()
        await self.client.connect(self.manager.api_port)
        await self.client.close()
        await self.manager.stop()
        with self.assertRaises(RuntimeError):
            await self.client.list_outbounds()
        await self.manager.start()
        await self.client.connect(self.manager.api_port)
        self.assertEqual([item.tag for item in await self.client.list_outbounds()], ["blocked"])
