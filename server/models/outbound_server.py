"""One remote server from a subscription, independent of the core's config format."""

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from secrets import token_hex
from typing import Literal
from uuid import UUID

from .serialization import SECRET, JsonValue


class OutboundProtocol(StrEnum):
    VLESS = "vless"
    SHADOWSOCKS = "shadowsocks"
    HYSTERIA = "hysteria"


class OutboundTransport(StrEnum):
    TCP = "tcp"
    GRPC = "grpc"
    WS = "ws"
    XHTTP = "xhttp"
    HYSTERIA = "hysteria"


class OutboundSecurity(StrEnum):
    NONE = "none"
    TLS = "tls"
    REALITY = "reality"


class VlessFlow(StrEnum):
    NONE = ""
    VISION = "xtls-rprx-vision"
    VISION_UDP443 = "xtls-rprx-vision-udp443"


class ShadowsocksMethod(StrEnum):
    NONE = "none"
    AES_128_GCM = "aes-128-gcm"
    AES_256_GCM = "aes-256-gcm"
    CHACHA20_POLY1305 = "chacha20-ietf-poly1305"
    XCHACHA20_POLY1305 = "xchacha20-ietf-poly1305"
    BLAKE3_AES_128_GCM = "2022-blake3-aes-128-gcm"
    BLAKE3_AES_256_GCM = "2022-blake3-aes-256-gcm"
    BLAKE3_CHACHA20_POLY1305 = "2022-blake3-chacha20-poly1305"


class UotVersion(IntEnum):
    V1 = 1
    V2 = 2


class GrpcMode(StrEnum):
    GUN = "gun"
    MULTI = "multi"
    GUNA = "guna"


class XhttpMode(StrEnum):
    AUTO = "auto"
    PACKET_UP = "packet-up"
    STREAM_UP = "stream-up"
    STREAM_ONE = "stream-one"


class FilterReason(StrEnum):
    """Why a server is filtered, see OutboundServer.filtered."""

    # The name matches a RegFilter.
    BY_REG_FILTER = "by_reg_filter"
    # The last check got no TCP connection within outbound_probe.PING_LIMIT.
    BY_PING = "by_ping"
    # Reserved for filtering by the subscription; not set yet.
    BY_SUBSCRIPTION = "by_subscription"


_REQUIRED = object()

# Fields named "<protocol>_*" belong to that protocol; values are defaults for the active one.
_PROTOCOL_DEFAULTS: dict[str, object] = {
    "vless_uuid": _REQUIRED,
    "vless_encryption": "none",
    "vless_flow": VlessFlow.NONE,
    "vless_extra": dict,
    "shadowsocks_password": _REQUIRED,
    "shadowsocks_method": _REQUIRED,
    "shadowsocks_udp_over_tcp": False,
    "shadowsocks_uot_version": None,
    "shadowsocks_extra": dict,
    "hysteria_auth": _REQUIRED,
    "hysteria_version": 2,
    "hysteria_extra": dict,
}


@dataclass(kw_only=True)
class OutboundServer:
    """Normalized connection data; no fetching, parsing or conversion to a core config.

    One flat structure for every protocol: only fields prefixed with the active
    protocol's name are set, those of other protocols stay None. Construction
    fills defaults of the active protocol and rejects fields of the others.

    subscription_id is an application identifier, not a subscription access URL.
    source_tag is the provider's tag, not a globally unique outbound identifier.
    Extension dictionaries retain provider-specific settings without interpreting them.
    Health fields (ping, speed, rating, tests) come from the server's own checks,
    not from the subscription.
    Fields marked SECRET are hidden from repr and never sent to clients.
    """

    # Application ID, independent of the provider's name and protocol credentials.
    id: str = field(default_factory=lambda: token_hex(6))
    name: str
    address: str
    port: int
    protocol: OutboundProtocol
    subscription_id: str | None = None
    source_tag: str | None = None

    transport: OutboundTransport = OutboundTransport.TCP
    security: OutboundSecurity = OutboundSecurity.NONE
    server_name: str | None = None
    fingerprint: str | None = None
    alpn: tuple[str, ...] = ()
    public_key: str | None = None
    short_id: str | None = None
    spider_x: str | None = None
    allow_insecure: bool | None = None

    host: str | None = None
    path: str | None = None
    service_name: str | None = None
    grpc_mode: GrpcMode | None = None
    xhttp_mode: XhttpMode | None = None

    # JSON options such as xhttpSettings.extra.xmux, sockopt or finalmask.
    # Secret: the original stream may include hysteriaSettings.auth or auth headers.
    stream_options: dict[str, JsonValue] = field(default_factory=dict, repr=False, metadata=SECRET)
    # Unmapped URI fields, e.g. concurrency, x-durev-block, x-durev-prio.
    extra_params: dict[str, str] = field(default_factory=dict, repr=False, metadata=SECRET)

    vless_uuid: UUID | None = field(default=None, repr=False, metadata=SECRET)
    # Encryption may include algorithm parameters/key material, not just "none".
    vless_encryption: str | None = field(default=None, repr=False, metadata=SECRET)
    vless_flow: VlessFlow | None = None
    vless_extra: dict[str, JsonValue] | None = field(default=None, repr=False, metadata=SECRET)

    shadowsocks_password: str | None = field(default=None, repr=False, metadata=SECRET)
    shadowsocks_method: ShadowsocksMethod | None = None
    shadowsocks_udp_over_tcp: bool | None = None
    shadowsocks_uot_version: UotVersion | None = None
    shadowsocks_extra: dict[str, JsonValue] | None = field(
        default=None, repr=False, metadata=SECRET
    )

    hysteria_auth: str | None = field(default=None, repr=False, metadata=SECRET)
    # Only Hysteria 2 is supported.
    hysteria_version: Literal[2] | None = None
    hysteria_extra: dict[str, JsonValue] | None = field(default=None, repr=False, metadata=SECRET)

    # Health measured by the server; None until the server is checked.
    # Round-trip time in milliseconds.
    ping: int | None = None
    # Download speed in bytes per second.
    speed: int | None = None
    # Overall score for choosing a server; higher is better.
    rating: int | None = None
    # Results of ServerSettings.outbound_tests: alias -> passed.
    tests: dict[str, bool] | None = None
    # Why the server is filtered, or None. A filtered server cannot be connected,
    # and checks skip it, except BY_PING: those are checked again to come back.
    # A connected server that gets BY_REG_FILTER is disconnected.
    # BY_REG_FILTER takes precedence; it is computed from RegFilters on every
    # read of the store and never stored.
    filtered: FilterReason | None = None
    # The core's main route goes through this server; true for at most one server.
    # Changed by handlers/core.py only, kept across subscription refreshes.
    is_connected: bool = False

    def __post_init__(self):
        for name in ("ping", "speed", "rating"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer")
        if self.tests is not None and not all(
            type(passed) is bool for passed in self.tests.values()
        ):
            raise ValueError("tests must map test aliases to booleans")
        for name, default in _PROTOCOL_DEFAULTS.items():
            value = getattr(self, name)
            if not name.startswith(f"{self.protocol.value}_"):
                if value is not None:
                    raise ValueError(f"{name} does not apply to {self.protocol.value} servers")
            elif value is None:
                if default is _REQUIRED:
                    raise ValueError(f"{name} is required for {self.protocol.value} servers")
                setattr(self, name, default() if callable(default) else default)
