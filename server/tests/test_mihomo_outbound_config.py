"""Compatibility checks for model overrides and raw subscription extensions."""

import unittest
from copy import deepcopy
from uuid import UUID

from server.cores.mihomo.outbound_config import outbound_config
from server.models import (
    OutboundProtocol,
    OutboundSecurity,
    OutboundServer,
    OutboundTransport,
    ShadowsocksMethod,
    UotVersion,
    XhttpMode,
)


def vless(**options):
    return OutboundServer(
        name="sample",
        address="example.com",
        port=443,
        protocol=OutboundProtocol.VLESS,
        vless_uuid=UUID(int=1),
        **options,
    )


class MihomoOutboundConfigTests(unittest.TestCase):
    def convert(self, model):
        before = deepcopy(model)
        result = outbound_config(model, model.id)
        self.assertEqual(model, before)
        return result

    def test_reality_and_tls_overrides(self):
        model = vless(
            security=OutboundSecurity.REALITY,
            server_name="model.example",
            fingerprint="firefox",
            allow_insecure=False,
            alpn=("h2",),
            public_key="model-key",
            short_id="",
            stream_options={
                "realitySettings": {
                    "serverName": "raw.example",
                    "fingerprint": "chrome",
                    "allowInsecure": True,
                    "alpn": ["http/1.1"],
                    "publicKey": "raw-key",
                    "password": "fallback-key",
                    "shortId": "abcd",
                    "spiderX": "/",
                    "show": True,
                }
            },
        )
        config = self.convert(model)
        self.assertEqual(config["reality-opts"], {"public-key": "model-key", "short-id": ""})
        self.assertEqual(config["servername"], "model.example")
        self.assertEqual(config["client-fingerprint"], "firefox")
        self.assertEqual(config["alpn"], ["h2"])
        self.assertIs(config["skip-cert-verify"], False)

    def test_reality_key_aliases(self):
        for options, expected in (
            ({"publicKey": "public", "password": "fallback"}, "public"),
            ({"password": "fallback"}, "fallback"),
        ):
            with self.subTest(options=options):
                model = vless(
                    security=OutboundSecurity.REALITY, stream_options={"realitySettings": options}
                )
                self.assertEqual(
                    self.convert(model)["reality-opts"], {"public-key": expected, "short-id": ""}
                )

    def test_ws_and_grpc_overrides(self):
        ws = vless(
            transport=OutboundTransport.WS,
            host="model.example",
            path="/model",
            stream_options={
                "wsSettings": {
                    "path": "/raw",
                    "headers": {"Host": "raw.example", "Other": "retained"},
                    "maxEarlyData": 2048,
                    "earlyDataHeaderName": "Sec-WebSocket-Protocol",
                }
            },
        )
        self.assertEqual(
            self.convert(ws)["ws-opts"],
            {
                "path": "/model",
                "headers": {"Host": "model.example", "Other": "retained"},
                "max-early-data": 2048,
                "early-data-header-name": "Sec-WebSocket-Protocol",
            },
        )
        grpc = vless(
            transport=OutboundTransport.GRPC,
            service_name="model-service",
            stream_options={"grpcSettings": {"serviceName": "raw", "multiMode": False}},
        )
        self.assertEqual(self.convert(grpc)["grpc-opts"], {"grpc-service-name": "model-service"})

    def test_xhttp_precedence_and_ranges(self):
        model = vless(
            transport=OutboundTransport.XHTTP,
            path="/model",
            xhttp_mode=XhttpMode.STREAM_ONE,
            stream_options={
                "xhttpSettings": {
                    "path": "/raw",
                    "host": "top.example",
                    "mode": "auto",
                    "extra": {"host": "extra.example", "scMaxEachPostBytes": 1000},
                    "xPaddingBytes": "100-200",
                    "scMinPostsIntervalMs": 10,
                    "xmux": {
                        "maxConcurrency": "8-16",
                        "maxConnections": 2,
                        "cMaxReuseTimes": 3,
                        "hMaxRequestTimes": 4,
                        "hMaxReusableSecs": 5,
                        "hKeepAlivePeriod": 6,
                    },
                }
            },
        )
        self.assertEqual(
            self.convert(model)["xhttp-opts"],
            {
                "path": "/model",
                "host": "top.example",
                "mode": "stream-one",
                "sc-max-each-post-bytes": "1000",
                "x-padding-bytes": "100-200",
                "sc-min-posts-interval-ms": "10",
                "reuse-settings": {
                    "max-concurrency": "8-16",
                    "max-connections": "2",
                    "c-max-reuse-times": "3",
                    "h-max-request-times": "4",
                    "h-max-reusable-secs": "5",
                    "h-keep-alive-period": 6,
                },
            },
        )

    def test_hysteria_tls_and_quic(self):
        model = OutboundServer(
            name="hysteria",
            address="example.com",
            port=443,
            protocol=OutboundProtocol.HYSTERIA,
            hysteria_auth="credential",
            transport=OutboundTransport.HYSTERIA,
            security=OutboundSecurity.TLS,
            server_name="model.example",
            fingerprint="chrome",
            stream_options={
                "tlsSettings": {
                    "serverName": "raw.example",
                    "fingerprint": "firefox",
                    "allowInsecure": False,
                    "alpn": ["h3"],
                },
                "hysteriaSettings": {"auth": "ignored", "version": 2},
                "finalmask": {
                    "quicParams": {
                        "brutalUp": 100,
                        "brutalDown": 200,
                        "initStreamReceiveWindow": 1024,
                    }
                },
            },
        )
        self.assertEqual(
            self.convert(model),
            {
                "name": model.id,
                "server": "example.com",
                "port": 443,
                "udp": True,
                "type": "hysteria2",
                "password": "credential",
                "sni": "model.example",
                "skip-cert-verify": False,
                "alpn": ["h3"],
                "up": 100,
                "down": 200,
                "initial-stream-receive-window": 1024,
            },
        )

    def test_shadowsocks_uot(self):
        model = OutboundServer(
            name="ss",
            address="example.com",
            port=443,
            protocol=OutboundProtocol.SHADOWSOCKS,
            shadowsocks_password="credential",
            shadowsocks_method=ShadowsocksMethod.AES_128_GCM,
            shadowsocks_udp_over_tcp=True,
            shadowsocks_uot_version=UotVersion.V2,
        )
        self.assertEqual(
            self.convert(model),
            {
                "name": model.id,
                "server": "example.com",
                "port": 443,
                "udp": True,
                "type": "ss",
                "cipher": "aes-128-gcm",
                "password": "credential",
                "udp-over-tcp": True,
                "udp-over-tcp-version": 2,
            },
        )

    def test_unsupported_nested_options_are_not_silently_dropped(self):
        for model in (
            vless(
                security=OutboundSecurity.TLS,
                stream_options={"tlsSettings": {"unknown": "credential"}},
            ),
            vless(
                transport=OutboundTransport.WS,
                stream_options={"wsSettings": {"unknown": "credential"}},
            ),
            vless(
                transport=OutboundTransport.GRPC,
                stream_options={"grpcSettings": {"multiMode": True}},
            ),
            vless(
                transport=OutboundTransport.XHTTP,
                stream_options={"xhttpSettings": {"xmux": {"unknown": "credential"}}},
            ),
            vless(stream_options={"rawSettings": {}, "tcpSettings": {"header": {"type": "none"}}}),
        ):
            with self.subTest(transport=model.transport, security=model.security):
                before = deepcopy(model)
                with self.assertRaises(ValueError) as raised:
                    outbound_config(model, model.id)
                self.assertNotIn("credential", str(raised.exception))
                self.assertEqual(model, before)
