"""Build Mihomo proxies from normalized models and supported Xray extensions."""

from copy import deepcopy

from ...models import (
    GrpcMode,
    OutboundProtocol,
    OutboundSecurity,
    OutboundServer,
    OutboundTransport,
    VlessFlow,
)


def outbound_config(server: OutboundServer, name: str) -> dict:
    """Convert one server without modifying it; reject unsupported extensions."""
    if type(server.port) is not int or not 1 <= server.port <= 65535:
        raise ValueError("Invalid outbound port")
    # Only the active protocol's extras are set.
    extra = server.vless_extra or server.shadowsocks_extra or server.hysteria_extra or {}
    if extra.keys() - {"email", "level"}:
        raise ValueError("Unsupported protocol extensions for Mihomo")

    # Helpers consume this private copy. Anything left over is unsupported.
    stream = deepcopy(server.stream_options)
    stream.pop("network", None)
    stream.pop("security", None)
    if server.protocol == OutboundProtocol.VLESS:
        options = _vless_config(server, stream)
    elif server.protocol == OutboundProtocol.SHADOWSOCKS:
        options = _shadowsocks_config(server, stream)
    elif server.protocol == OutboundProtocol.HYSTERIA:
        options = _hysteria_config(server, stream)
    else:
        raise ValueError("Unsupported outbound protocol")
    if stream:
        raise ValueError("Unsupported Xray stream options for Mihomo")

    return {"name": name, "server": server.address, "port": server.port, "udp": True, **options}


def _rename_options(options: dict, names: dict[str, str]) -> dict:
    """Translate raw extension keys only; normalized fields are assigned directly."""
    if options.keys() - names.keys():
        raise ValueError("Unsupported subscription options for Mihomo")
    return {names[key]: value for key, value in options.items()}


def _shadowsocks_config(server: OutboundServer, stream: dict) -> dict:
    if (
        server.transport != OutboundTransport.TCP
        or server.security != OutboundSecurity.NONE
        or stream
    ):
        raise ValueError("Shadowsocks stream extensions are not supported by this adapter")
    config = {
        "type": "ss",
        "cipher": server.shadowsocks_method,
        "password": server.shadowsocks_password,
        "udp-over-tcp": server.shadowsocks_udp_over_tcp,
    }
    if server.shadowsocks_uot_version is not None:
        config["udp-over-tcp-version"] = int(server.shadowsocks_uot_version)
    return config


def _tls_config(server: OutboundServer, options: dict, *, server_name_key: str) -> dict:
    config = _rename_options(
        options,
        {
            "serverName": server_name_key,
            "allowInsecure": "skip-cert-verify",
            "alpn": "alpn",
        },
    )
    # Explicit model fields take precedence over raw subscription options.
    if server.server_name is not None:
        config[server_name_key] = server.server_name
    if server.allow_insecure is not None:
        config["skip-cert-verify"] = server.allow_insecure
    if server.alpn:
        config["alpn"] = list(server.alpn)
    return config


def _vless_config(server: OutboundServer, stream: dict) -> dict:
    if server.vless_flow == VlessFlow.VISION_UDP443:
        raise ValueError("Mihomo does not support the Xray vision-udp443 flow")
    if server.grpc_mode not in (None, GrpcMode.GUN):
        raise ValueError("Mihomo does not support Xray gRPC multi/guna modes")
    config = {
        "type": "vless",
        "uuid": str(server.vless_uuid),
        "encryption": server.vless_encryption,
        "flow": server.vless_flow,
        "tls": server.security != OutboundSecurity.NONE,
        "network": server.transport.value,
    }
    security = stream.pop(f"{server.security.value}Settings", {})
    if server.security == OutboundSecurity.REALITY:
        config["reality-opts"] = _reality_config(server, security)
    if "fingerprint" in security or server.fingerprint is not None:
        fingerprint = security.pop("fingerprint", None)
        config["client-fingerprint"] = (
            server.fingerprint if server.fingerprint is not None else fingerprint
        )
    config.update(_tls_config(server, security, server_name_key="servername"))
    config.update(_vless_transport_config(server, stream))
    return config


def _reality_config(server: OutboundServer, options: dict) -> dict:
    public_key = server.public_key or options.get("publicKey") or options.get("password")
    short_id = server.short_id if server.short_id is not None else options.get("shortId", "")
    # spiderX/show have no counterpart in Mihomo.
    for key in ("publicKey", "password", "shortId", "spiderX", "show"):
        options.pop(key, None)
    if not public_key:
        raise ValueError("Reality requires a public key")
    return {"public-key": public_key, "short-id": short_id}


def _vless_transport_config(server: OutboundServer, stream: dict) -> dict:
    match server.transport:
        case OutboundTransport.TCP:
            raw = stream.pop("rawSettings", None)
            tcp = stream.pop("tcpSettings", {})
            if raw is not None and tcp and raw != tcp:
                raise ValueError("Conflicting raw/TCP options")
            options = raw if raw is not None else tcp
            if options and options != {"header": {"type": "none"}}:
                raise ValueError("Unsupported TCP options for Mihomo")
            return {}
        case OutboundTransport.WS:
            options = stream.pop("wsSettings", {})
            host = server.host or options.pop("host", None)
            config = _rename_options(
                options,
                {
                    "path": "path",
                    "headers": "headers",
                    "maxEarlyData": "max-early-data",
                    "earlyDataHeaderName": "early-data-header-name",
                },
            )
            if server.path is not None:
                config["path"] = server.path
            if host:
                config.setdefault("headers", {})["Host"] = host
            return {"ws-opts": config}
        case OutboundTransport.GRPC:
            options = stream.pop("grpcSettings", {})
            if options.pop("multiMode", False):
                raise ValueError("Mihomo does not support Xray gRPC multi mode")
            config = _rename_options(options, {"serviceName": "grpc-service-name"})
            if server.service_name is not None:
                config["grpc-service-name"] = server.service_name
            return {"grpc-opts": config}
        case OutboundTransport.XHTTP:
            return {"xhttp-opts": _xhttp_config(server, stream.pop("xhttpSettings", {}))}
        case _:
            raise ValueError("Unsupported VLESS transport for Mihomo")


def _xhttp_config(server: OutboundServer, options: dict) -> dict:
    # Top-level settings override the corresponding values in extra.
    extra = options.pop("extra", {})
    options = {**extra, **options}
    xmux = options.pop("xmux", None)
    config = _rename_options(
        options,
        {
            "path": "path",
            "host": "host",
            "mode": "mode",
            "headers": "headers",
            "noGRPCHeader": "no-grpc-header",
            "xPaddingBytes": "x-padding-bytes",
            "scMaxEachPostBytes": "sc-max-each-post-bytes",
            "scMinPostsIntervalMs": "sc-min-posts-interval-ms",
        },
    )
    if server.path is not None:
        config["path"] = server.path
    if server.host is not None:
        config["host"] = server.host
    if server.xhttp_mode is not None:
        config["mode"] = server.xhttp_mode.value
    # Mihomo represents these ranges as strings, even for a single number.
    for key in ("x-padding-bytes", "sc-max-each-post-bytes", "sc-min-posts-interval-ms"):
        if key in config:
            config[key] = str(config[key])
    if xmux is not None:
        config["reuse-settings"] = _xmux_config(xmux)
    return config


def _xmux_config(options: dict) -> dict:
    config = _rename_options(
        options,
        {
            "maxConcurrency": "max-concurrency",
            "maxConnections": "max-connections",
            "cMaxReuseTimes": "c-max-reuse-times",
            "hMaxRequestTimes": "h-max-request-times",
            "hMaxReusableSecs": "h-max-reusable-secs",
            "hKeepAlivePeriod": "h-keep-alive-period",
        },
    )
    return {
        key: value if key == "h-keep-alive-period" else str(value) for key, value in config.items()
    }


def _hysteria_config(server: OutboundServer, stream: dict) -> dict:
    if server.hysteria_version != 2 or server.transport not in (
        OutboundTransport.TCP,
        OutboundTransport.HYSTERIA,
    ):
        raise ValueError("Mihomo adapter supports Hysteria 2 only")
    if server.security != OutboundSecurity.TLS:
        raise ValueError("Hysteria 2 requires TLS")
    security = stream.pop("tlsSettings", {})
    # QUIC uses its own TLS implementation, not a browser fingerprint.
    security.pop("fingerprint", None)
    config = {"type": "hysteria2", "password": server.hysteria_auth}
    config.update(_tls_config(server, security, server_name_key="sni"))
    transport = stream.pop("hysteriaSettings", {})
    if transport.keys() - {"auth", "version"}:
        raise ValueError("Unsupported Hysteria transport options for Mihomo")
    finalmask = stream.pop("finalmask", {})
    quic = finalmask.pop("quicParams", {})
    if finalmask:
        raise ValueError("Xray transport masks are not supported by this adapter")
    config.update(
        _rename_options(
            quic,
            {
                "brutalUp": "up",
                "brutalDown": "down",
                "initStreamReceiveWindow": "initial-stream-receive-window",
                "maxStreamReceiveWindow": "max-stream-receive-window",
                "initConnectionReceiveWindow": "initial-connection-receive-window",
                "maxConnectionReceiveWindow": "max-connection-receive-window",
            },
        )
    )
    return config
