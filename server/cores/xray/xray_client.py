"""Application-level Xray control. Await lifecycle operations sequentially."""

from uuid import uuid4

from ...models import CoreState, OutboundServer
from ..core_client import CoreClient
from .grpc_generated.app.proxyman.config_pb2 import ReceiverConfig
from .grpc_generated.app.router.config_pb2 import RoutingRule
from .grpc_generated.common.net.address_pb2 import IPOrDomain
from .grpc_generated.common.net.port_pb2 import PortList, PortRange
from .grpc_generated.core.config_pb2 import InboundHandlerConfig
from .grpc_generated.proxy.socks.config_pb2 import ServerConfig
from .outbound_protobuf import build_outbound
from .xray_grpc_client import XrayGrpcClient, typed_message
from .xray_process_manager import XrayProcessManager


class XrayClient(CoreClient):
    def __init__(self):
        self.process_manager = XrayProcessManager()
        self.grpc_client = XrayGrpcClient()
        self.proxy_port: int | None = None
        self.test_port: int | None = None
        self._inbounds: dict[str, str] = {}
        self._outbounds: dict[str, str] = {}

    def _require_started(self):
        if self.process_manager.status().state != CoreState.RUNNING:
            raise RuntimeError("Start the service first")

    @staticmethod
    def _validate_port(port: int):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Port must be an integer between 1 and 65535")

    def check_outbound_server_config(self, server: OutboundServer) -> None:
        build_outbound(server, server.id)

    async def service_start(self, proxy_port: int, test_port: int) -> None:
        self._validate_port(proxy_port)
        self._validate_port(test_port)
        if proxy_port == test_port:
            raise ValueError("Main and test ports must differ")
        if self.process_manager.status().state != CoreState.STOPPED:
            raise RuntimeError("Stop the service before starting it again")
        try:
            await self.process_manager.start()
            await self.grpc_client.connect(self.process_manager.api_port)
            await self._set_inbound("main", proxy_port)
            await self._set_inbound("test", test_port)
        except Exception:
            await self.service_stop()
            raise

    async def service_stop(self) -> None:
        try:
            await self.grpc_client.close()
        finally:
            await self.process_manager.stop()
            self.proxy_port = self.test_port = None
            self._inbounds.clear()
            self._outbounds.clear()

    async def _set_inbound(self, role: str, port: int):
        self._validate_port(port)
        current = self.proxy_port if role == "main" else self.test_port
        other = self.test_port if role == "main" else self.proxy_port
        if port == other or port == self.process_manager.api_port:
            raise ValueError("Port is already used by another service endpoint")
        if port == current:
            return
        tag = f"{role}-in-{uuid4().hex}"
        old = self._inbounds.get(role)
        await self.grpc_client.add_inbound(
            InboundHandlerConfig(
                tag=tag,
                proxy_settings=typed_message(
                    ServerConfig(udp_enabled=True, address=IPOrDomain(ip=b"\x7f\x00\x00\x01"))
                ),
                receiver_settings=typed_message(
                    ReceiverConfig(
                        listen=IPOrDomain(ip=b"\x7f\x00\x00\x01"),
                        port_list=PortList(range=[PortRange(From=port, To=port)]),
                    )
                ),
            )
        )
        inbounds = {**self._inbounds, role: tag}
        try:
            await self._route(inbounds, self._outbounds)
        except Exception:
            await self.grpc_client.remove_inbound(tag)
            raise
        self._inbounds = inbounds
        if role == "main":
            self.proxy_port = port
        else:
            self.test_port = port
        if old is not None:
            await self.grpc_client.remove_inbound(old)

    async def outbound_connect(self, server_id: str) -> None:
        self._require_started()
        await self._connect("main", server_id)

    async def outbound_disconnect(self) -> None:
        self._require_started()
        await self._block("main")

    async def outbound_register(self, servers: list[OutboundServer]) -> None:
        self._require_started()
        self._validate_server_ids(servers)
        configs = [build_outbound(server, server.id) for server in servers]
        await self.outbound_delete_all()
        for config in configs:
            await self.grpc_client.add_outbound(config)

    async def outbound_delete_all(self) -> None:
        self._require_started()
        await self._route(self._inbounds, {})
        for outbound in await self.grpc_client.list_outbounds():
            if outbound.tag != "blocked":
                await self.grpc_client.remove_outbound(outbound.tag)
        self._outbounds.clear()

    async def test_connect(self, server_id: str) -> None:
        self._require_started()
        await self._connect("test", server_id)

    async def _connect(self, role: str, server_id: str):
        tags = {outbound.tag for outbound in await self.grpc_client.list_outbounds()}
        if server_id == "blocked" or server_id not in tags:
            raise ValueError("Server is not registered")
        outbounds = {**self._outbounds, role: server_id}
        await self._route(self._inbounds, outbounds)
        self._outbounds = outbounds

    async def test_stop(self) -> None:
        self._require_started()
        await self._block("test")

    async def _block(self, role: str):
        outbounds = {other: tag for other, tag in self._outbounds.items() if other != role}
        await self._route(self._inbounds, outbounds)
        self._outbounds = outbounds

    async def _route(self, inbounds: dict[str, str], outbounds: dict[str, str]):
        await self.grpc_client.replace_rules(
            [
                RoutingRule(rule_tag=role, inbound_tag=[tag], tag=outbounds.get(role, "blocked"))
                for role, tag in inbounds.items()
            ]
        )
