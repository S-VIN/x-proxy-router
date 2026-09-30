"""One listener of the core that accepts local traffic, independent of the core's config format."""

from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import ip_address
from uuid import uuid4

from .serialization import SECRET


class InboundType(StrEnum):
    # SOCKS5 and HTTP proxy on one port, UDP included.
    PROXY = "proxy"


# The port of the inbound created with the database; clients may change or delete it.
DEFAULT_PROXY_PORT = 20808

_REQUIRED = object()

# Fields named "<type>_*" belong to that type; values are defaults for the active one.
_TYPE_DEFAULTS: dict[str, object] = {
    "proxy_listen": "127.0.0.1",
    "proxy_port": _REQUIRED,
    "proxy_username": None,
    "proxy_password": None,
}


class InboundFieldError(ValueError):
    """An invalid value of one field; field names it for clients."""

    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, kw_only=True)
class InboundServer:
    """Where the core accepts traffic that goes out through the connected server.

    One flat structure for every type: only fields prefixed with the active
    type's name are set, those of other types stay None. Construction fills
    defaults of the active type and rejects fields of the others.
    Fields marked SECRET are hidden from repr and never sent to clients.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    type: InboundType
    # False keeps the inbound stored without a listener in the core.
    enabled: bool = True

    # IP address to listen on; 0.0.0.0 or :: accepts connections from the network.
    proxy_listen: str | None = None
    proxy_port: int | None = None
    # Both set or both None; None lets anyone who reaches the port use the proxy.
    proxy_username: str | None = None
    proxy_password: str | None = field(default=None, repr=False, metadata=SECRET)

    # Why the core does not listen, set by the server; None while the listener
    # works or the inbound is disabled.
    error: str | None = None

    def __post_init__(self):
        if not self.id:
            raise InboundFieldError("Inbound id must not be empty", "id")
        if not isinstance(self.type, InboundType):
            raise InboundFieldError("Unknown inbound type", "type")
        if type(self.enabled) is not bool:
            raise InboundFieldError("Enabled must be true or false", "enabled")
        if self.error is not None and not isinstance(self.error, str):
            raise InboundFieldError("Error must be a string", "error")
        for name, default in _TYPE_DEFAULTS.items():
            value = getattr(self, name)
            if not name.startswith(f"{self.type.value}_"):
                if value is not None:
                    raise InboundFieldError(
                        f"{name} does not apply to {self.type.value} inbounds", name
                    )
            elif value is None and default is not None:
                if default is _REQUIRED:
                    raise InboundFieldError(
                        f"{name} is required for {self.type.value} inbounds", name
                    )
                object.__setattr__(self, name, default)
        if self.type == InboundType.PROXY:
            self._check_proxy()

    def _check_proxy(self) -> None:
        try:
            listen = ip_address(str(self.proxy_listen))
        except ValueError:
            raise InboundFieldError(
                "Listen address must be an IP address", "proxy_listen"
            ) from None
        object.__setattr__(self, "proxy_listen", listen.compressed)
        port = self.proxy_port
        if type(port) is not int or not 1 <= port <= 65535:
            raise InboundFieldError("Port must be an integer between 1 and 65535", "proxy_port")
        username, password = self.proxy_username, self.proxy_password
        if (username is None) != (password is None):
            field_name = "proxy_password" if password is None else "proxy_username"
            raise InboundFieldError("Username and password are set together", field_name)
        if username is not None:
            if not isinstance(username, str) or not username or ":" in username:
                raise InboundFieldError(
                    "Username must be a non-empty string without a colon", "proxy_username"
                )
            if not isinstance(password, str) or not password:
                raise InboundFieldError("Password must be a non-empty string", "proxy_password")
