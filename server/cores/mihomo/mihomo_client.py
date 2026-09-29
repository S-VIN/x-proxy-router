"""Application-level Mihomo control. Await lifecycle calls sequentially."""

import asyncio
import socket

from ...models import CoreState, OutboundServer
from ..core_client import CoreClient
from .mihomo_process_manager import MihomoError, MihomoProcessManager
from .mihomo_rest_client import MihomoRestClient
from .outbound_config import outbound_config


class MihomoClient(CoreClient):
    def __init__(self):
        self.process_manager = MihomoProcessManager()
        self.rest_client = MihomoRestClient()
        self.proxy_port: int | None = None
        self.test_port: int | None = None

    def check_outbound_server_config(self, server: OutboundServer) -> None:
        outbound_config(server, server.id)

    async def service_start(self, proxy_port: int, test_port: int) -> None:
        self._validate_port(proxy_port)
        self._validate_port(test_port)
        if proxy_port == test_port:
            raise ValueError("Main and test ports must differ")
        if self.process_manager.status().state != CoreState.STOPPED:
            raise RuntimeError("Stop the service before starting it again")
        self._check_port_available(proxy_port)
        self._check_port_available(test_port)

        try:
            await self.process_manager.start()
            assert self.process_manager.api_port is not None
            assert self.process_manager.api_secret is not None
            await self.rest_client.connect(
                self.process_manager.api_port, self.process_manager.api_secret
            )
            if self.process_manager.api_port in (proxy_port, test_port):
                raise ValueError("Proxy port conflicts with the API port")
            self.proxy_port, self.test_port = proxy_port, test_port
            await self.outbound_register([])
            await self._check_listener(proxy_port)
            await self._check_listener(test_port)
        except Exception:
            await self.service_stop()
            raise

    async def service_stop(self) -> None:
        try:
            await self.rest_client.close()
        finally:
            await self.process_manager.stop()
            self.proxy_port = self.test_port = None

    async def outbound_register(self, servers: list[OutboundServer]) -> None:
        """Replace all servers and reset both groups to REJECT."""
        self._require_started()
        self._validate_server_ids(servers)
        await self.rest_client.replace_config(self._build_config(servers))

    async def outbound_delete_all(self) -> None:
        await self.outbound_register([])

    async def outbound_connect(self, server_id: str) -> None:
        self._require_started()
        await self.rest_client.select_proxy("main", server_id)

    async def outbound_disconnect(self) -> None:
        self._require_started()
        await self.rest_client.select_proxy("main", "REJECT")

    async def test_connect(self, server_id: str) -> None:
        self._require_started()
        await self.rest_client.select_proxy("test", server_id)

    async def test_stop(self) -> None:
        self._require_started()
        await self.rest_client.select_proxy("test", "REJECT")

    def _build_config(self, servers: list[OutboundServer]) -> dict:
        """Build a fresh config from the bootstrap template, fixed ports and servers."""
        config = self.process_manager._generate_config()
        config["proxies"] = [outbound_config(server, server.id) for server in servers]
        choices = ["REJECT", *(server.id for server in servers)]
        config["listeners"] = []
        config["proxy-groups"] = []
        for name, port in (("main", self.proxy_port), ("test", self.test_port)):
            config["listeners"].append(
                {
                    "name": name,
                    "type": "socks",
                    "listen": "127.0.0.1",
                    "port": port,
                    "udp": True,
                }
            )
            config["proxy-groups"].append(
                {
                    "name": name,
                    "type": "select",
                    "proxies": choices.copy(),
                }
            )
        return config

    def _require_started(self) -> None:
        if self.process_manager.status().state != CoreState.RUNNING:
            raise RuntimeError("Start the service first")

    @staticmethod
    def _validate_port(port: int) -> None:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Port must be an integer between 1 and 65535")

    @staticmethod
    def _check_port_available(port: int) -> None:
        with socket.socket() as tcp, socket.socket(type=socket.SOCK_DGRAM) as udp:
            tcp.bind(("127.0.0.1", port))
            udp.bind(("127.0.0.1", port))

    @staticmethod
    async def _check_listener(port: int) -> None:
        async with asyncio.timeout(5):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                writer.write(b"\x05\x01\x00")  # SOCKS5, one method: no authentication.
                await writer.drain()
                if await reader.readexactly(2) != b"\x05\x00":
                    raise MihomoError("Mihomo SOCKS listener did not become ready")
            finally:
                writer.close()
                await writer.wait_closed()
