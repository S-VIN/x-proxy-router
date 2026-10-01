"""Application-level Xray control. Await lifecycle operations sequentially."""

import asyncio
from ipaddress import ip_address
from uuid import uuid4

import grpc

from ...models import CoreState, InboundServer, OutboundServer
from ..core_client import CoreClient, InboundError, proxy_address
from .grpc_generated.app.proxyman.config_pb2 import ReceiverConfig
from .grpc_generated.app.router.config_pb2 import RoutingRule
from .grpc_generated.common.net.address_pb2 import IPOrDomain
from .grpc_generated.common.net.port_pb2 import PortList, PortRange
from .grpc_generated.core.config_pb2 import InboundHandlerConfig
from .grpc_generated.proxy.socks.config_pb2 import AuthType, ServerConfig
from .outbound_protobuf import build_outbound
from .xray_grpc_client import XrayGrpcClient, typed_message
from .xray_process_manager import XrayProcessManager


def _socks_inbound(
    tag: str, listen: str, port: int, accounts: dict[str, str]
) -> InboundHandlerConfig:
    """A SOCKS5 inbound; Xray also accepts HTTP proxy requests on it."""
    address = ip_address(listen)
    settings = ServerConfig(udp_enabled=True)
    # UDP ASSOCIATE answers with this address; on all interfaces Xray uses the connection's.
    if not address.is_unspecified:
        settings.address.CopyFrom(IPOrDomain(ip=address.packed))
    if accounts:
        settings.auth_type = AuthType.PASSWORD
        settings.accounts.update(accounts)
    return InboundHandlerConfig(
        tag=tag,
        proxy_settings=typed_message(settings),
        receiver_settings=typed_message(
            ReceiverConfig(
                listen=IPOrDomain(ip=address.packed),
                port_list=PortList(range=[PortRange(From=port, To=port)]),
            )
        ),
    )


def inbound_handler(inbound: InboundServer) -> InboundHandlerConfig:
    """The Xray inbound for an application inbound; ValueError for unsupported types."""
    listen, port = proxy_address(inbound)
    accounts = {}
    if inbound.proxy_username is not None and inbound.proxy_password is not None:
        accounts[inbound.proxy_username] = inbound.proxy_password
    return _socks_inbound(inbound_tag(inbound.id), listen, port, accounts)


def inbound_tag(inbound_id: str) -> str:
    return f"inbound-{inbound_id}"


class XrayClient(CoreClient):
    """Changes of inbounds, outbounds and routes are serialized, so an inbound
    change may run while a server is checked.
    """

    def __init__(self):
        self.process_manager = XrayProcessManager()
        self.grpc_client = XrayGrpcClient()
        self.test_port: int | None = None
        # Tag of the test endpoint's inbound.
        self._test_inbound: str | None = None
        self._inbounds: dict[str, InboundServer] = {}
        # Route ("main", "test") -> server id; a missing route is blocked.
        self._outbounds: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def _require_started(self):
        if self.process_manager.status().state != CoreState.RUNNING:
            raise RuntimeError("Start the service first")

    @staticmethod
    def _validate_port(port: int):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Port must be an integer between 1 and 65535")

    def check_outbound_server_config(self, server: OutboundServer) -> None:
        build_outbound(server, server.id)

    def check_inbound_config(self, inbound: InboundServer) -> None:
        inbound_handler(inbound)

    async def service_start(self, test_port: int) -> None:
        self._validate_port(test_port)
        if self.process_manager.status().state != CoreState.STOPPED:
            raise RuntimeError("Stop the service before starting it again")
        try:
            await self.process_manager.start()
            assert self.process_manager.api_port is not None
            await self.grpc_client.connect(self.process_manager.api_port)
            if test_port == self.process_manager.api_port:
                raise ValueError("Test port conflicts with the API port")
            tag = f"test-in-{uuid4().hex}"
            await self.grpc_client.add_inbound(_socks_inbound(tag, "127.0.0.1", test_port, {}))
            self._test_inbound, self.test_port = tag, test_port
            await self._route(self._outbounds, self._inbounds)
        except Exception:
            await self.service_stop()
            raise

    async def service_stop(self) -> None:
        try:
            await self.grpc_client.close()
        finally:
            await self.process_manager.stop()
            self.test_port = self._test_inbound = None
            self._inbounds.clear()
            self._outbounds.clear()

    async def inbound_set(self, inbound: InboundServer) -> None:
        self._require_started()
        self._validate_inbound_id(inbound.id)
        handler = inbound_handler(inbound)
        async with self._lock:
            old = self._inbounds.get(inbound.id)
            if old is not None and inbound_handler(old) == handler:
                return
            self._check_inbound_available(old, inbound)
            inbounds = {**self._inbounds, inbound.id: inbound}
            if old is None:
                # The route first, so the new listener's traffic never leaves unrouted.
                await self._route(self._outbounds, inbounds)
            else:
                # The same port cannot be opened twice, so the old listener goes first.
                await self.grpc_client.remove_inbound(handler.tag)
            added = False
            try:
                await self.grpc_client.add_inbound(handler)
                added = True
                await self._check_inbound_listening(inbound)
            except BaseException as error:
                if added:
                    await self.grpc_client.remove_inbound(handler.tag)
                if old is not None:
                    await self.grpc_client.add_inbound(inbound_handler(old))
                else:
                    await self._route(self._outbounds, self._inbounds)
                if isinstance(error, grpc.RpcError):
                    _, port = proxy_address(inbound)
                    raise InboundError(
                        f"The core could not listen on port {port}", "proxy_port"
                    ) from None
                raise
            self._inbounds = inbounds

    async def inbound_delete(self, inbound_id: str) -> None:
        self._require_started()
        async with self._lock:
            if inbound_id not in self._inbounds:
                return
            inbounds = {id_: item for id_, item in self._inbounds.items() if id_ != inbound_id}
            await self.grpc_client.remove_inbound(inbound_tag(inbound_id))
            self._inbounds = inbounds
            await self._route(self._outbounds, inbounds)

    async def outbound_connect(self, server_id: str) -> None:
        await self._connect("main", server_id)

    async def outbound_disconnect(self) -> None:
        await self._block("main")

    async def outbound_register(self, servers: list[OutboundServer]) -> None:
        self._require_started()
        self._validate_server_ids(servers)
        configs = [build_outbound(server, server.id) for server in servers]
        async with self._lock:
            await self._delete_outbounds()
            for config in configs:
                await self.grpc_client.add_outbound(config)

    async def outbound_delete_all(self) -> None:
        self._require_started()
        async with self._lock:
            await self._delete_outbounds()

    async def _delete_outbounds(self):
        await self._route({}, self._inbounds)
        self._outbounds.clear()
        for outbound in await self.grpc_client.list_outbounds():
            if outbound.tag != "blocked":
                await self.grpc_client.remove_outbound(outbound.tag)

    async def test_connect(self, server_id: str) -> None:
        await self._connect("test", server_id)

    async def _connect(self, role: str, server_id: str):
        self._require_started()
        async with self._lock:
            tags = {outbound.tag for outbound in await self.grpc_client.list_outbounds()}
            if server_id == "blocked" or server_id not in tags:
                raise ValueError("Server is not registered")
            outbounds = {**self._outbounds, role: server_id}
            await self._route(outbounds, self._inbounds)
            self._outbounds = outbounds

    async def test_stop(self) -> None:
        await self._block("test")

    async def _block(self, role: str):
        self._require_started()
        async with self._lock:
            outbounds = {other: tag for other, tag in self._outbounds.items() if other != role}
            await self._route(outbounds, self._inbounds)
            self._outbounds = outbounds

    async def _route(self, outbounds: dict[str, str], inbounds: dict[str, InboundServer]):
        """Send the test inbound and all application inbounds to their routes' servers.

        Traffic no rule matches goes to the first outbound, blocked.
        """
        rules = []
        if self._test_inbound is not None:
            rules.append(
                RoutingRule(
                    rule_tag="test",
                    inbound_tag=[self._test_inbound],
                    tag=outbounds.get("test", "blocked"),
                )
            )
        if inbounds:
            rules.append(
                RoutingRule(
                    rule_tag="main",
                    inbound_tag=[inbound_tag(inbound_id) for inbound_id in inbounds],
                    tag=outbounds.get("main", "blocked"),
                )
            )
        await self.grpc_client.replace_rules(rules)
