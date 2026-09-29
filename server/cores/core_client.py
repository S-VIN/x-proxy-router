"""Core-independent service control contract."""

import re
from abc import ABC, abstractmethod

from ..models import OutboundServer


class CoreClient(ABC):
    # SOCKS5 port of the test endpoint on 127.0.0.1; None while the service is stopped.
    test_port: int | None = None

    @staticmethod
    def _validate_server_ids(servers: list[OutboundServer]) -> None:
        ids = [server.id for server in servers]
        reserved = {
            "main",
            "test",
            "DIRECT",
            "REJECT",
            "REJECT-DROP",
            "PASS",
            "GLOBAL",
            "COMPATIBLE",
            "blocked",
            "api",
        }
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate server IDs")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]+", value) or value in reserved for value in ids):
            raise ValueError("Invalid or reserved server ID")

    @abstractmethod
    def check_outbound_server_config(self, server: OutboundServer) -> None:
        """Raise ValueError if the core cannot build its config from the server's parameters.

        Only converts the parameters: no network access, no core process needed,
        nothing is changed. Server availability is checked elsewhere.
        """
        ...

    @abstractmethod
    async def service_start(self, proxy_port: int, test_port: int) -> None: ...

    @abstractmethod
    async def service_stop(self) -> None: ...

    @abstractmethod
    async def outbound_register(self, servers: list[OutboundServer]) -> None:
        """Replace ALL registered servers and reset both routes to blocked.

        Empty list deletes all. IDs must be unique. Xray replacement is not atomic.
        """
        ...

    @abstractmethod
    async def outbound_delete_all(self) -> None:
        """Delete application servers and block both routes; keep listeners."""
        ...

    @abstractmethod
    async def outbound_connect(self, server_id: str) -> None:
        """Select an already registered server by its application ID."""
        ...

    @abstractmethod
    async def outbound_disconnect(self) -> None:
        """Block new main traffic, keeping its listener and registrations."""
        ...

    @abstractmethod
    async def test_connect(self, server_id: str) -> None:
        """Select an already registered server for the test endpoint."""
        ...

    @abstractmethod
    async def test_stop(self) -> None:
        """Block new test traffic, keeping its listener and registrations."""
        ...
