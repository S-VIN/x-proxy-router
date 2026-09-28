"""Load servers from a subscription URL or a direct VLESS link without stored state."""

import asyncio
import base64
import json
import zlib
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from .models import (
    GrpcMode,
    OutboundProtocol,
    OutboundSecurity,
    OutboundServer,
    OutboundTransport,
    ShadowsocksMethod,
    SubscriptionLink,
    UotVersion,
    VlessFlow,
    XhttpMode,
)

__all__ = ["SubscriptionError", "load_subscription"]

_MAX_SIZE = 10 * 1024 * 1024


class SubscriptionError(RuntimeError):
    """A subscription could not be downloaded or parsed."""

    def __init__(self, subscription_id: str):
        super().__init__(f"Cannot load subscription {subscription_id}")
        self.subscription_id = subscription_id


async def load_subscription(link: str | SubscriptionLink) -> list[OutboundServer]:
    """Detect HTTP(S) subscriptions or direct VLESS links and return all servers.

    Responses can contain plain/Base64 VLESS lists or Xray JSON profiles.
    SubscriptionLink preserves its id; a string gets a new subscription id.
    """
    url = link.url if isinstance(link, SubscriptionLink) else link
    scheme = urlsplit(url).scheme
    if scheme not in ("http", "https", "vless"):
        raise ValueError("Expected an HTTP(S) subscription or VLESS link")
    if scheme in ("http", "https") and isinstance(link, str):
        link = SubscriptionLink(url=link)
    subscription_id = link.id if isinstance(link, SubscriptionLink) else str(uuid4())
    try:
        body = url if scheme == "vless" else await asyncio.to_thread(_download, url)
        return _parse_subscription(body, subscription_id)
    except Exception:  # noqa: BLE001
        # URLs, response bodies and parser exceptions may contain credentials.
        raise SubscriptionError(subscription_id) from None


def _download(url: str) -> str:
    # Providers choose the response format by User-Agent.
    request = Request(url, headers={"User-Agent": "v2rayN/7.0", "Accept-Encoding": "gzip, deflate"})
    with urlopen(request, timeout=30) as response:
        body = response.read(_MAX_SIZE + 1)
        encoding = response.headers.get("Content-Encoding", "identity").lower()
    # Some providers compress even when asked for identity, so trust the magic bytes too.
    if encoding in ("gzip", "deflate") or body.startswith(b"\x1f\x8b"):
        # wbits=47 accepts gzip and zlib headers; max_length limits decompression bombs.
        body = zlib.decompressobj(wbits=47).decompress(body, _MAX_SIZE + 1)
    elif encoding != "identity":
        raise ValueError("Unsupported content encoding")
    if len(body) > _MAX_SIZE:
        raise ValueError("Subscription response is too large")
    return body.decode("utf-8-sig")


def _endpoint(address, port):
    if not isinstance(address, str) or not address.strip():
        raise ValueError("Missing server address")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid server port")
    return address, port


def _boolean(value):
    if value in (True, "true", "1"):
        return True
    if value in (False, "false", "0"):
        return False
    raise ValueError("Invalid boolean")


def _uri_server(uri: str, subscription_id: str) -> OutboundServer:
    parsed = urlsplit(uri)
    if parsed.scheme != "vless" or not parsed.username or parsed.password is not None:
        raise ValueError("Expected a VLESS URI")
    address, port = _endpoint(parsed.hostname, parsed.port)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    params = dict(pairs)
    if len(pairs) != len(params):
        raise ValueError("Duplicate URI parameters")
    transport = OutboundTransport(params.pop("type", "tcp").replace("raw", "tcp"))
    mode = params.pop("mode", None)
    grpc_mode = GrpcMode(mode) if mode is not None and transport == OutboundTransport.GRPC else None
    xhttp_mode = (
        XhttpMode(mode) if mode is not None and transport == OutboundTransport.XHTTP else None
    )
    if mode is not None and grpc_mode is None and xhttp_mode is None:
        params["mode"] = mode
    insecure = params.pop("allowInsecure", None)
    server = OutboundServer(
        name=unquote(parsed.fragment) or address,
        address=address,
        port=port,
        subscription_id=subscription_id,
        protocol=OutboundProtocol.VLESS,
        vless_uuid=UUID(unquote(parsed.username)),
        vless_encryption=params.pop("encryption", "none"),
        vless_flow=VlessFlow(params.pop("flow", "")),
        transport=transport,
        security=OutboundSecurity(params.pop("security", "none")),
        server_name=params.pop("sni", None),
        fingerprint=params.pop("fp", None),
        alpn=tuple(filter(None, params.pop("alpn", "").split(","))),
        public_key=params.pop("pbk", None),
        short_id=params.pop("sid", None),
        spider_x=params.pop("spx", None),
        allow_insecure=_boolean(insecure) if insecure is not None else None,
        host=params.pop("host", None),
        path=params.pop("path", None),
        service_name=params.pop("serviceName", None),
        grpc_mode=grpc_mode,
        xhttp_mode=xhttp_mode,
    )
    server.extra_params = params
    return server


def _stream_fields(stream: dict) -> dict:
    network = stream.get("network", "tcp")
    transport = OutboundTransport("tcp" if network == "raw" else network)
    security = OutboundSecurity(stream.get("security", "none"))
    tls = stream.get(
        "realitySettings" if security == OutboundSecurity.REALITY else "tlsSettings", {}
    )
    options = stream.get(f"{transport.value}Settings", {})
    mode = options.get("mode")
    return {
        "transport": transport,
        "security": security,
        "server_name": tls.get("serverName"),
        "fingerprint": tls.get("fingerprint"),
        "alpn": tuple(tls.get("alpn", [])),
        "public_key": tls.get("publicKey"),
        "short_id": tls.get("shortId"),
        "spider_x": tls.get("spiderX"),
        "allow_insecure": tls.get("allowInsecure"),
        "host": options.get("host", options.get("headers", {}).get("Host")),
        "path": options.get("path"),
        "service_name": options.get("serviceName"),
        "grpc_mode": (
            GrpcMode(mode) if mode else GrpcMode.MULTI if options.get("multiMode") else GrpcMode.GUN
        )
        if transport == OutboundTransport.GRPC
        else None,
        "xhttp_mode": XhttpMode(mode) if mode and transport == OutboundTransport.XHTTP else None,
        # Preserve original nested settings, including XHTTP extras and finalmask.
        "stream_options": deepcopy(stream),
    }


def _json_servers(outbound: dict, name: str, subscription_id: str) -> list[OutboundServer]:
    protocol = outbound["protocol"]
    if protocol in ("freedom", "blackhole", "dns", "loopback"):
        return []
    settings = outbound.get("settings", {})
    stream = outbound.get("streamSettings", {})
    # (endpoint, OutboundServer fields of the protocol)
    entries: list[tuple[dict, dict[str, Any]]] = []
    if protocol == "vless":
        for endpoint in settings["vnext"]:
            for user in endpoint["users"]:
                config = {
                    "vless_uuid": UUID(user["id"]),
                    "vless_encryption": user.get("encryption", "none"),
                    "vless_flow": VlessFlow(user.get("flow", "")),
                    "vless_extra": {
                        k: deepcopy(v)
                        for k, v in user.items()
                        if k not in ("id", "encryption", "flow")
                    },
                }
                entries.append((endpoint, config))
    elif protocol == "shadowsocks":
        aliases = {
            "plain": "none",
            "chacha20-poly1305": "chacha20-ietf-poly1305",
            "xchacha20-poly1305": "xchacha20-ietf-poly1305",
            "aead_aes_128_gcm": "aes-128-gcm",
            "aead_aes_256_gcm": "aes-256-gcm",
            "aead_chacha20_poly1305": "chacha20-ietf-poly1305",
            "aead_xchacha20_poly1305": "xchacha20-ietf-poly1305",
        }
        for endpoint in settings.get("servers", [settings]):
            method = endpoint["method"].lower()
            version = endpoint.get("uotVersion", endpoint.get("UoTVersion"))
            config = {
                "shadowsocks_password": endpoint["password"],
                "shadowsocks_method": ShadowsocksMethod(aliases.get(method, method)),
                "shadowsocks_udp_over_tcp": _boolean(endpoint.get("uot", False)),
                "shadowsocks_uot_version": UotVersion(version) if version else None,
                "shadowsocks_extra": {
                    k: deepcopy(v)
                    for k, v in endpoint.items()
                    if k
                    not in (
                        "address",
                        "port",
                        "password",
                        "method",
                        "uot",
                        "uotVersion",
                        "UoTVersion",
                    )
                },
            }
            entries.append((endpoint, config))
    elif protocol == "hysteria":
        options = stream.get("hysteriaSettings", {})
        if settings.get("version") != 2 or options.get("version", 2) != 2:
            raise ValueError("Only Hysteria 2 is supported")
        entries.append(
            (
                settings,
                {
                    "hysteria_auth": options["auth"],
                    "hysteria_extra": {
                        k: deepcopy(v)
                        for k, v in settings.items()
                        if k not in ("address", "port", "version")
                    },
                },
            )
        )
    else:
        raise ValueError("Unsupported outbound protocol")
    servers = []
    for endpoint, config in entries:
        address, port = _endpoint(endpoint["address"], endpoint["port"])
        servers.append(
            OutboundServer(
                name=name or outbound.get("tag") or address,
                address=address,
                port=port,
                subscription_id=subscription_id,
                source_tag=outbound.get("tag"),
                protocol=OutboundProtocol(protocol),
                **config,
                **_stream_fields(stream),
            )
        )
    return servers


def _parse_subscription(body: str, subscription_id: str) -> list[OutboundServer]:
    """Return every remote server; fail on unsupported/malformed data, never silently drop it."""
    body = body.lstrip("\ufeff").strip()
    if not body:
        return []
    if not body.startswith(("[", "{")) and not body.startswith("vless://"):
        encoded = "".join(body.split())
        body = (
            base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            .decode("utf-8-sig")
            .strip()
        )
    if body.startswith(("[", "{")):
        profiles = json.loads(body)
        if isinstance(profiles, dict):
            profiles = [profiles]
        servers = []
        for profile in profiles:
            outbounds = profile.get("outbounds")
            if outbounds is None:
                outbounds = [profile] if "protocol" in profile else None
            if outbounds is None:
                raise ValueError("Expected an Xray profile or outbound")
            for outbound in outbounds:
                servers.extend(_json_servers(outbound, profile.get("remarks", ""), subscription_id))
        return servers
    return [
        _uri_server(line.strip(), subscription_id) for line in body.splitlines() if line.strip()
    ]
