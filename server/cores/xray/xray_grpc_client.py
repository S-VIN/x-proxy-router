"""Async Xray API client. Use in the event loop that opened the connection."""

import asyncio
from collections.abc import Sequence

import grpc
from google.protobuf.message import Message

from .grpc_generated.app.proxyman.command import command_pb2 as handlers
from .grpc_generated.app.proxyman.command.command_pb2_grpc import HandlerServiceStub
from .grpc_generated.app.router.command import command_pb2 as routing_messages
from .grpc_generated.app.router.command.command_pb2_grpc import RoutingServiceStub
from .grpc_generated.app.router.config_pb2 import Config as RouterConfig
from .grpc_generated.app.router.config_pb2 import RoutingRule
from .grpc_generated.common.serial.typed_message_pb2 import TypedMessage
from .grpc_generated.core.config_pb2 import InboundHandlerConfig, OutboundHandlerConfig

_GRPC_TIMEOUT = 5


def typed_message(message: Message) -> TypedMessage:
    """Pack a protobuf config into Xray's TypedMessage (not protobuf Any)."""
    # Generated message classes always set DESCRIPTOR; the base class leaves it None.
    descriptor = message.DESCRIPTOR
    assert descriptor is not None
    return TypedMessage(type=descriptor.full_name, value=message.SerializeToString())


class XrayGrpcClient:
    """Thin asynchronous wrapper around Xray gRPC methods."""

    def __init__(self):
        self._channel = None
        self._handlers = None
        self._routing = None

    async def connect(self, port: int) -> None:
        """Open a loopback connection and wait for gRPC readiness."""
        await self.close()
        self._channel = grpc.aio.insecure_channel(
            f"127.0.0.1:{port}",
            options=(("grpc.enable_http_proxy", 0),),
        )
        try:
            async with asyncio.timeout(_GRPC_TIMEOUT):
                await self._channel.channel_ready()
        except Exception:
            await self.close()
            raise
        self._handlers = HandlerServiceStub(self._channel)
        self._routing = RoutingServiceStub(self._channel)

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
        self._channel = self._handlers = self._routing = None

    @property
    def handlers(self) -> HandlerServiceStub:
        """Raw API for calls not covered by convenience methods; pass timeout explicitly."""
        if self._handlers is None:
            raise RuntimeError("XrayGrpcClient is not connected")
        return self._handlers

    @property
    def routing(self) -> RoutingServiceStub:
        if self._routing is None:
            raise RuntimeError("XrayGrpcClient is not connected")
        return self._routing

    async def add_inbound(self, config: InboundHandlerConfig) -> None:
        await self.handlers.AddInbound(
            handlers.AddInboundRequest(inbound=config), timeout=_GRPC_TIMEOUT
        )

    async def remove_inbound(self, tag: str) -> None:
        await self.handlers.RemoveInbound(
            handlers.RemoveInboundRequest(tag=tag), timeout=_GRPC_TIMEOUT
        )

    async def list_inbounds(self) -> list[InboundHandlerConfig]:
        response = await self.handlers.ListInbounds(
            handlers.ListInboundsRequest(), timeout=_GRPC_TIMEOUT
        )
        return list(response.inbounds)

    async def add_outbound(self, config: OutboundHandlerConfig) -> None:
        await self.handlers.AddOutbound(
            handlers.AddOutboundRequest(outbound=config), timeout=_GRPC_TIMEOUT
        )

    async def remove_outbound(self, tag: str) -> None:
        await self.handlers.RemoveOutbound(
            handlers.RemoveOutboundRequest(tag=tag), timeout=_GRPC_TIMEOUT
        )

    async def list_outbounds(self) -> list[OutboundHandlerConfig]:
        response = await self.handlers.ListOutbounds(
            handlers.ListOutboundsRequest(), timeout=_GRPC_TIMEOUT
        )
        return list(response.outbounds)

    async def replace_rules(self, rules: Sequence[RoutingRule]) -> None:
        """Replace all rules; also clears balancers. Does not change domainStrategy."""
        await self._set_rules(rules, append=False)

    async def append_rules(self, rules: Sequence[RoutingRule]) -> None:
        await self._set_rules(rules, append=True)

    async def _set_rules(self, rules: Sequence[RoutingRule], append: bool):
        await self.routing.AddRule(
            routing_messages.AddRuleRequest(
                config=typed_message(RouterConfig(rule=rules)),
                shouldAppend=append,
            ),
            timeout=_GRPC_TIMEOUT,
        )

    async def remove_rule(self, tag: str) -> None:
        await self.routing.RemoveRule(
            routing_messages.RemoveRuleRequest(ruleTag=tag), timeout=_GRPC_TIMEOUT
        )

    async def list_rules(self) -> list[routing_messages.ListRuleItem]:
        """Return rule tags and outbound tags, not full rule conditions."""
        response = await self.routing.ListRule(
            routing_messages.ListRuleRequest(), timeout=_GRPC_TIMEOUT
        )
        return list(response.rules)

    async def test_route(
        self, context: routing_messages.RoutingContext
    ) -> routing_messages.RoutingContext:
        return await self.routing.TestRoute(
            routing_messages.TestRouteRequest(RoutingContext=context),
            timeout=_GRPC_TIMEOUT,
        )
