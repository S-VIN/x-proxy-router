"""Convert subscription models to Xray JSON without mutating the models."""

from copy import deepcopy

from ...models import OutboundProtocol, OutboundServer


def outbound_config(server: OutboundServer, tag: str) -> dict:
    stream = deepcopy(server.stream_options)
    stream.update(network=server.transport.value, security=server.security.value)
    if server.security.value != "none":
        security = stream.setdefault(f"{server.security.value}Settings", {})
        for key, value in {
            "serverName": server.server_name, "fingerprint": server.fingerprint,
            "allowInsecure": server.allow_insecure,
            **({"publicKey": server.public_key, "shortId": server.short_id,
                "spiderX": server.spider_x} if server.security.value == "reality" else {}),
        }.items():
            if value is not None:
                security[key] = value
        if server.alpn:
            security["alpn"] = list(server.alpn)
    transport = server.transport.value
    if transport == "ws":
        options = stream.setdefault("wsSettings", {})
        if server.path is not None:
            options["path"] = server.path
        if server.host is not None:
            options.setdefault("headers", {})["Host"] = server.host
    elif transport == "grpc":
        options = stream.setdefault("grpcSettings", {})
        if server.service_name is not None:
            options["serviceName"] = server.service_name
        if server.grpc_mode is not None:
            options["multiMode"] = server.grpc_mode.value == "multi"
    elif transport == "xhttp":
        options = stream.setdefault("xhttpSettings", {})
        for key, value in {"path": server.path, "host": server.host, "mode": server.xhttp_mode}.items():
            if value is not None:
                options[key] = value
    endpoint = {"address": server.address, "port": server.port}
    if server.protocol == OutboundProtocol.VLESS:
        user = deepcopy(server.vless_extra or {})
        user.update(id=str(server.vless_uuid), encryption=server.vless_encryption,
                    flow=server.vless_flow)
        settings = {"vnext": [{**endpoint, "users": [user]}]}
    elif server.protocol == OutboundProtocol.SHADOWSOCKS:
        remote = deepcopy(server.shadowsocks_extra or {})
        remote.update(**endpoint, password=server.shadowsocks_password,
                      method=server.shadowsocks_method, uot=server.shadowsocks_udp_over_tcp)
        if server.shadowsocks_uot_version is not None:
            remote["uotVersion"] = int(server.shadowsocks_uot_version)
        settings = {"servers": [remote]}
    elif server.protocol == OutboundProtocol.HYSTERIA:
        settings = deepcopy(server.hysteria_extra or {})
        settings.update(**endpoint, version=server.hysteria_version)
        stream.setdefault("hysteriaSettings", {}).update(auth=server.hysteria_auth,
                                                          version=server.hysteria_version)
    else:
        raise ValueError("Unsupported outbound settings")
    return {"tag": tag, "protocol": server.protocol.value,
            "settings": settings, "streamSettings": stream}
