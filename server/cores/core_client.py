"""Core-independent service control contract."""

import asyncio
import errno
import re
import socket
from abc import ABC, abstractmethod
from contextlib import suppress
from ipaddress import ip_address

from ..models import InboundServer, InboundType, OutboundServer

# Names the cores use for their own objects: groups, listeners, special outbounds.
_RESERVED_IDS = frozenset(
    {
        "main",
        "test",
        "DIRECT",
        "REJECT",
        "REJECT-DROP",
        "PASS",
        "GLOBAL",
        "COMPATIBLE",
    }
)
_ADDRESS_IN_USE = {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)}
_ADDRESS_NOT_AVAILABLE = {
    errno.EADDRNOTAVAIL,
    getattr(errno, "WSAEADDRNOTAVAIL", errno.EADDRNOTAVAIL),
}
_ACCESS_DENIED = {errno.EACCES, getattr(errno, "WSAEACCES", errno.EACCES)}


class InboundError(Exception):
    """The core cannot listen as the inbound asks.

    The message is safe to send to clients; field names the inbound field to
    change: proxy_port or proxy_listen.
    """

    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field


def proxy_address(inbound: InboundServer) -> tuple[str, int]:
    """The listen address and port of a proxy inbound."""
    if inbound.type != InboundType.PROXY:
        raise ValueError(f"The core does not support {inbound.type} inbounds")
    assert inbound.proxy_listen is not None and inbound.proxy_port is not None
    return inbound.proxy_listen, inbound.proxy_port


class CoreClient(ABC):
    # SOCKS5 port of the test endpoint on 127.0.0.1; None while the service is stopped.
    test_port: int | None = None

    @staticmethod
    def _validate_server_ids(servers: list[OutboundServer]) -> None:
        ids = [server.id for server in servers]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate server IDs")
        if any(
            not re.fullmatch(r"[A-Za-z0-9_-]+", value) or value in _RESERVED_IDS for value in ids
        ):
            raise ValueError("Invalid or reserved server ID")

    @staticmethod
    def _validate_inbound_id(inbound_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", inbound_id) or inbound_id in _RESERVED_IDS:
            raise ValueError("Invalid or reserved inbound ID")

    @staticmethod
    def _check_inbound_available(old: InboundServer | None, new: InboundServer) -> None:
        """Raise InboundError if the new listener's address or port cannot be bound.

        The port is checked when it is new; while it stays the same, the core
        holds it, so only a changed address is checked, on a free port.
        """
        listen, port = proxy_address(new)
        if old is not None and proxy_address(old) == (listen, port):
            return
        same_port = old is not None and proxy_address(old)[1] == port
        family = socket.AF_INET6 if ip_address(listen).version == 6 else socket.AF_INET
        try:
            for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                with socket.socket(family, kind) as probe:
                    probe.bind((listen, 0 if same_port else port))
        except OSError as error:
            if error.errno in _ADDRESS_NOT_AVAILABLE:
                raise InboundError(
                    f"Address {listen} is not available on this computer", "proxy_listen"
                ) from None
            if error.errno in _ADDRESS_IN_USE:
                raise InboundError(f"Port {port} is already in use", "proxy_port") from None
            if error.errno in _ACCESS_DENIED:
                raise InboundError(
                    f"Port {port} needs administrator rights or is reserved", "proxy_port"
                ) from None
            raise InboundError(f"Cannot listen on port {port}", "proxy_port") from None

    @staticmethod
    async def _check_inbound_listening(inbound: InboundServer) -> None:
        """Raise InboundError unless a SOCKS5 proxy answers at the inbound's address."""
        listen, port = proxy_address(inbound)
        address = ip_address(listen)
        # A listener on all interfaces is reached through loopback.
        if address.is_unspecified:
            listen = "::1" if address.version == 6 else "127.0.0.1"
        answer = b""
        try:
            async with asyncio.timeout(5):
                reader, writer = await asyncio.open_connection(listen, port)
                try:
                    # SOCKS5 with two methods: no authentication, username and password.
                    writer.write(b"\x05\x02\x00\x02")
                    await writer.drain()
                    answer = await reader.readexactly(2)
                finally:
                    writer.close()
                    with suppress(OSError):
                        await writer.wait_closed()
        except (OSError, TimeoutError, asyncio.IncompleteReadError):
            pass
        if answer[:1] != b"\x05":
            raise InboundError(f"The core could not listen on port {port}", "proxy_port")

    @abstractmethod
    def check_outbound_server_config(self, server: OutboundServer) -> None:
        """Raise ValueError if the core cannot build its config from the server's parameters.

        Only converts the parameters: no network access, no core process needed,
        nothing is changed. Server availability is checked elsewhere.
        """
        ...

    @abstractmethod
    def check_inbound_config(self, inbound: InboundServer) -> None:
        """Raise ValueError if the core cannot build a listener from the inbound's parameters.

        No network access, no core process needed, nothing is changed.
        """
        ...

    @abstractmethod
    async def service_start(self, test_port: int) -> None:
        """Start the core with the test endpoint only: no inbounds, no servers."""
        ...

    @abstractmethod
    async def service_stop(self) -> None: ...

    @abstractmethod
    async def inbound_set(self, inbound: InboundServer) -> None:
        """Start the inbound's listener, or replace the running one with the same id.

        Its traffic takes the main route (outbound_connect, outbound_disconnect).
        Registered servers and both routes are kept, so a running server check
        and the connection are not interrupted; an unchanged listener keeps its
        connections. Raises InboundError if the address or port cannot be
        listened on; the previous listener with this id is then kept as it was.
        """
        ...

    @abstractmethod
    async def inbound_delete(self, inbound_id: str) -> None:
        """Stop the inbound's listener; an unknown id is ignored."""
        ...

    @abstractmethod
    async def outbound_register(self, servers: list[OutboundServer]) -> None:
        """Replace ALL registered servers and reset both routes to blocked; keep inbounds.

        Empty list deletes all. IDs must be unique.
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
