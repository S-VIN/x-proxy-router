"""Application-level Mihomo control. Await lifecycle calls sequentially."""

import asyncio
import socket
from collections.abc import Collection
from contextlib import ExitStack

from ...models import CoreState, InboundServer, OutboundServer, RoutingAction, RoutingRule
from ...models.pattern import WILDCARD
from ..core_client import CoreClient, proxy_address
from .mihomo_process_manager import MihomoError, MihomoProcessManager
from .mihomo_rest_client import MihomoRestClient
from .outbound_config import outbound_config

_BLOCKED = "REJECT"
_ACTION_TARGETS = {
    RoutingAction.PROXY: "main",
    RoutingAction.DIRECT: "DIRECT",
    RoutingAction.BLOCK: _BLOCKED,
}
# Ports the OS may offer before one is free for TCP and UDP and not reserved.
_FREE_PORT_ATTEMPTS = 20


def inbound_config(inbound: InboundServer) -> dict:
    """A Mihomo listener for the inbound, named by its id; ValueError for unsupported types."""
    listen, port = proxy_address(inbound)
    config: dict = {
        "name": inbound.id,
        "type": "mixed",
        "listen": listen,
        "port": port,
        "udp": True,
    }
    if inbound.proxy_username is not None:
        config["users"] = [{"username": inbound.proxy_username, "password": inbound.proxy_password}]
    return config


def domain_regex(pattern: str) -> str:
    """The Mihomo DOMAIN-REGEX for a domain pattern; Mihomo ignores case itself.

    The regex matches the whole domain. Atomic groups take each part between
    wildcards at its first occurrence, as models.pattern does, so Mihomo's
    backtracking engine never retries them on long domains.
    """
    first, *parts = (part.replace(".", r"\.") for part in pattern.split(WILDCARD))
    if not parts:
        return f"^{first}$"
    *middle, last = parts
    return f"^{first}{''.join(f'(?>.*?{part})' for part in middle if part)}.*{last}$"


def routing_rule_config(rule: RoutingRule) -> str:
    """The Mihomo rule for a routing rule."""
    target = _ACTION_TARGETS[rule.action]
    if rule.reg == WILDCARD:
        # A domain regex would match IP destinations too, as their domain is empty.
        return f"MATCH,{target}"
    network = rule.network
    if network is not None:
        kind = "IP-CIDR" if network.version == 4 else "IP-CIDR6"
        # Without no-resolve Mihomo would look up every domain to compare its address,
        # sending DNS queries for proxied domains from this computer.
        return f"{kind},{network},{target},no-resolve"
    return f"DOMAIN-REGEX,{domain_regex(rule.reg)},{target}"


class MihomoClient(CoreClient):
    """Mihomo takes its whole config at once, so the client remembers what it applied.

    The registered servers, the inbounds, the routing rules and the server
    selected for each route are kept to build the next config. Changes of the
    config and of the routes are serialized, so an inbound change may run while
    a server is checked.
    """

    def __init__(self):
        self.process_manager = MihomoProcessManager()
        self.rest_client = MihomoRestClient()
        self.test_port: int | None = None
        self._servers: list[OutboundServer] = []
        self._inbounds: dict[str, InboundServer] = {}
        self._rules: list[RoutingRule] = []
        self._selected = {"main": _BLOCKED, "test": _BLOCKED}
        self._lock = asyncio.Lock()

    def check_outbound_server_config(self, server: OutboundServer) -> None:
        outbound_config(server, server.id)

    def check_inbound_config(self, inbound: InboundServer) -> None:
        inbound_config(inbound)

    async def service_start(self, reserved_ports: Collection[int] = ()) -> None:
        if self.process_manager.status().state != CoreState.STOPPED:
            raise RuntimeError("Stop the service before starting it again")

        try:
            await self.process_manager.start()
            assert self.process_manager.api_port is not None
            assert self.process_manager.api_secret is not None
            await self.rest_client.connect(
                self.process_manager.api_port, self.process_manager.api_secret
            )
            self.test_port = self._free_port({*reserved_ports, self.process_manager.api_port})
            await self.outbound_register([])
            await self._check_listener(self.test_port)
        except Exception:
            await self.service_stop()
            raise

    async def service_stop(self) -> None:
        try:
            await self.rest_client.close()
        finally:
            await self.process_manager.stop()
            self.test_port = None
            self._servers = []
            self._inbounds = {}
            self._rules = []
            self._selected = {"main": _BLOCKED, "test": _BLOCKED}

    async def outbound_register(self, servers: list[OutboundServer]) -> None:
        """Replace all servers and reset both groups to REJECT."""
        self._require_started()
        self._validate_server_ids(servers)
        selected = {"main": _BLOCKED, "test": _BLOCKED}
        async with self._lock:
            await self._apply(servers=servers, selected=selected)
            self._servers, self._selected = list(servers), selected

    async def outbound_delete_all(self) -> None:
        await self.outbound_register([])

    async def outbound_connect(self, server_id: str) -> None:
        await self._select("main", server_id)

    async def outbound_disconnect(self) -> None:
        await self._select("main", _BLOCKED)

    async def test_connect(self, server_id: str) -> None:
        await self._select("test", server_id)

    async def test_stop(self) -> None:
        await self._select("test", _BLOCKED)

    async def inbound_set(self, inbound: InboundServer) -> None:
        self._require_started()
        self._validate_inbound_id(inbound.id)
        listener = inbound_config(inbound)
        async with self._lock:
            old = self._inbounds.get(inbound.id)
            if old is not None and inbound_config(old) == listener:
                return
            self._check_inbound_available(old, inbound)
            inbounds = {**self._inbounds, inbound.id: inbound}
            await self._apply(inbounds=inbounds)
            try:
                # Mihomo accepts a listener it cannot open and only logs the error.
                await self._check_inbound_listening(inbound)
            except BaseException:
                await self._apply()
                raise
            self._inbounds = inbounds

    async def inbound_delete(self, inbound_id: str) -> None:
        self._require_started()
        async with self._lock:
            if inbound_id not in self._inbounds:
                return
            inbounds = {id_: item for id_, item in self._inbounds.items() if id_ != inbound_id}
            await self._apply(inbounds=inbounds)
            self._inbounds = inbounds

    async def routing_set(self, rules: list[RoutingRule]) -> None:
        self._require_started()
        rules = sorted(rules, key=lambda rule: rule.priority)
        async with self._lock:
            await self._apply(rules=rules)
            self._rules = rules

    async def _select(self, group: str, name: str) -> None:
        self._require_started()
        async with self._lock:
            await self.rest_client.select_proxy(group, name)
            self._selected[group] = name

    async def _apply(
        self,
        *,
        servers: list[OutboundServer] | None = None,
        inbounds: dict[str, InboundServer] | None = None,
        rules: list[RoutingRule] | None = None,
        selected: dict[str, str] | None = None,
    ) -> None:
        """Send a config with the given parts; omitted parts stay as applied."""
        await self.rest_client.replace_config(
            self._build_config(
                self._servers if servers is None else servers,
                self._inbounds if inbounds is None else inbounds,
                self._rules if rules is None else rules,
                self._selected if selected is None else selected,
            )
        )

    def _build_config(
        self,
        servers: list[OutboundServer],
        inbounds: dict[str, InboundServer],
        rules: list[RoutingRule],
        selected: dict[str, str],
    ) -> dict:
        """Build a fresh config from the bootstrap template, the test port and the parts.

        A select group starts at its first proxy, so the selected one goes first:
        a new config keeps both routes where they were. The test endpoint's rule
        goes before the routing rules, which then apply to the inbounds only.
        """
        config = self.process_manager._generate_config()
        config["proxies"] = [outbound_config(server, server.id) for server in servers]
        choices = [_BLOCKED, *(server.id for server in servers)]
        config["proxy-groups"] = [
            {
                "name": group,
                "type": "select",
                "proxies": [
                    selected[group],
                    *(name for name in choices if name != selected[group]),
                ],
            }
            for group in ("main", "test")
        ]
        config["listeners"] = [
            {
                "name": "test",
                "type": "socks",
                "listen": "127.0.0.1",
                "port": self.test_port,
                "udp": True,
            },
            *(inbound_config(inbound) for inbound in inbounds.values()),
        ]
        config["rules"] = [
            "IN-NAME,test,test",
            *(routing_rule_config(rule) for rule in rules),
            *(f"IN-NAME,{inbound_id},main" for inbound_id in inbounds),
            f"MATCH,{_BLOCKED}",
        ]
        return config

    def _require_started(self) -> None:
        if self.process_manager.status().state != CoreState.RUNNING:
            raise RuntimeError("Start the service first")

    @staticmethod
    def _free_port(excluded: Collection[int]) -> int:
        """A port on 127.0.0.1 free for TCP and UDP and not one of excluded."""
        # Rejected ports stay bound until the choice is made, so the OS offers others.
        with ExitStack() as rejected:
            for _ in range(_FREE_PORT_ATTEMPTS):
                tcp = rejected.enter_context(socket.socket())
                tcp.bind(("127.0.0.1", 0))
                port = tcp.getsockname()[1]
                if port in excluded:
                    continue
                with socket.socket(type=socket.SOCK_DGRAM) as udp:
                    try:
                        udp.bind(("127.0.0.1", port))
                    except OSError:
                        continue
                return port
        raise MihomoError("No free port for the test endpoint")

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
