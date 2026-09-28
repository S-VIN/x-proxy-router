import base64
import unittest
from copy import deepcopy
from unittest.mock import patch
from uuid import UUID

from server.cores.xray.grpc_generated.app.proxyman.config_pb2 import SenderConfig
from server.cores.xray.grpc_generated.proxy.shadowsocks_2022.config_pb2 import (
    ClientConfig as SS2022,
)
from server.cores.xray.grpc_generated.proxy.vless.account_pb2 import Account
from server.cores.xray.grpc_generated.proxy.vless.outbound.config_pb2 import Config as VlessConfig
from server.cores.xray.grpc_generated.transport.internet.hysteria.config_pb2 import (
    Config as Hysteria,
)
from server.cores.xray.grpc_generated.transport.internet.reality.config_pb2 import Config as Reality
from server.cores.xray.grpc_generated.transport.internet.splithttp.config_pb2 import Config as Xhttp
from server.cores.xray.grpc_generated.transport.internet.websocket.config_pb2 import Config as Ws
from server.cores.xray.outbound_protobuf import build_outbound
from server.models import (
    OutboundProtocol,
    OutboundSecurity,
    OutboundServer,
    OutboundTransport,
    ShadowsocksMethod,
    UotVersion,
    VlessFlow,
)


def remote(**kwargs):
    if 'protocol' not in kwargs:
        kwargs.update(protocol=OutboundProtocol.VLESS, vless_uuid=UUID(int=1),
                      vless_flow=VlessFlow.VISION)
    return OutboundServer(name='test', address='2001:db8::1', port=443, **kwargs)


def stream(config):
    return SenderConfig.FromString(config.sender_settings.value).stream_settings


class OutboundProtobufTests(unittest.TestCase):
    def test_vless_build_has_no_io_and_keeps_model(self):
        server = remote()
        before = deepcopy(server)
        with patch('asyncio.create_subprocess_exec', side_effect=AssertionError('subprocess')), \
             patch('builtins.open', side_effect=AssertionError('file I/O')), \
             patch('tempfile.TemporaryDirectory', side_effect=AssertionError('temporary directory')):
            config = build_outbound(server, 'chosen')
        endpoint = VlessConfig.FromString(config.proxy_settings.value).vnext
        self.assertEqual(endpoint.address.ip, bytes.fromhex('20010db8000000000000000000000001'))
        account = Account.FromString(endpoint.user.account.value)
        self.assertEqual(account.id, str(UUID(int=1)))
        self.assertEqual(account.flow, 'xtls-rprx-vision')
        self.assertEqual(account.encryption, 'none')
        self.assertEqual(config.tag, 'chosen')
        self.assertEqual(server, before)

    def test_reality_bytes_and_spider(self):
        server = remote(security=OutboundSecurity.REALITY,
            public_key=base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip('='),
            short_id='1234', server_name='example.com', fingerprint='chrome',
            spider_x='/path?p=10-20&c=2&keep=yes')
        options = Reality.FromString(stream(build_outbound(server, 'r')).security_settings[0].value)
        self.assertEqual(options.public_key, bytes(range(32)))
        self.assertEqual(options.short_id, b'\x12\x34' + bytes(6))
        self.assertEqual(list(options.spider_y), [10, 20, 2, 2, 0, 0, 0, 0, 0, 0])
        self.assertEqual(options.spider_x, '/path?keep=yes')
        self.assertEqual(options.Fingerprint, 'chrome')

    def test_xhttp_extra_ranges_and_defaults(self):
        server = remote(transport=OutboundTransport.XHTTP, path='/proxy',
            stream_options={'xhttpSettings': {'extra': {
                'xPaddingBytes': '100-200', 'sessionPlacement': 'header',
                'xmux': {'maxConcurrency': '2-4', 'hMaxRequestTimes': 20}}}})
        result = stream(build_outbound(server, 'x'))
        self.assertEqual(result.protocol_name, 'splithttp')
        config = Xhttp.FromString(result.transport_settings[0].settings.value)
        self.assertEqual(config.path, '/proxy')
        self.assertEqual(getattr(config.xPaddingBytes, 'from'), 100)
        self.assertEqual(config.xPaddingBytes.to, 200)
        self.assertEqual(config.xmux.maxConcurrency.to, 4)
        self.assertEqual(config.sessionKey, 'X-Session')
        self.assertEqual(config.xPaddingMethod, 'repeat-x')
        defaults = Xhttp.FromString(stream(build_outbound(remote(transport=OutboundTransport.XHTTP), 'x')).transport_settings[0].settings.value)
        self.assertEqual(defaults.xmux.hMaxRequestTimes.to, 900)
        self.assertEqual(defaults.xmux.hMaxReusableSecs.to, 3000)

    def test_websocket_host_and_early_data(self):
        server = remote(transport=OutboundTransport.WS, host='example.com', path='/ws?ed=2048&token=a')
        config = Ws.FromString(stream(build_outbound(server, 'ws')).transport_settings[0].settings.value)
        self.assertEqual(config.host, 'example.com')
        self.assertEqual(config.ed, 2048)
        self.assertEqual(config.path, '/ws?token=a')
        self.assertNotIn('Host', config.header)

    def test_shadowsocks2022_and_uot(self):
        server = remote(protocol=OutboundProtocol.SHADOWSOCKS,
            shadowsocks_method=ShadowsocksMethod.BLAKE3_AES_128_GCM,
            shadowsocks_password=base64.b64encode(bytes(16)).decode(),
            shadowsocks_udp_over_tcp=True, shadowsocks_uot_version=UotVersion.V2)
        config = SS2022.FromString(build_outbound(server, 'ss').proxy_settings.value)
        self.assertTrue(config.udp_over_tcp)
        self.assertEqual(config.udp_over_tcp_version, 2)
        self.assertEqual(config.method, '2022-blake3-aes-128-gcm')

    def test_hysteria_quic_and_timeout(self):
        server = remote(protocol=OutboundProtocol.HYSTERIA, hysteria_auth='example',
            transport=OutboundTransport.HYSTERIA, security=OutboundSecurity.TLS,
            stream_options={'finalmask': {'quicParams': {'congestion': 'bbr',
                'brutalUp': '10 mbps', 'udpHop': {'ports': '443,8443-8444', 'interval': '10-20'}}}})
        config = stream(build_outbound(server, 'hy'))
        hy = Hysteria.FromString(config.transport_settings[0].settings.value)
        self.assertEqual(hy.auth, 'example')
        self.assertEqual(hy.udp_idle_timeout, 60)
        self.assertEqual(config.quic_params.brutal_up, 10 * 1024 * 1024 // 8)
        self.assertEqual(list(config.quic_params.udp_hop.ports), [443, 8443, 8444])

    def test_unsupported_options_raise(self):
        for options in ({'unknownOption': True}, {'finalmask': {'tcp': [{'type': 'unknown'}]}}):
            with self.assertRaises(ValueError):
                build_outbound(remote(stream_options=options), 'bad')
        server = remote(security=OutboundSecurity.REALITY, public_key='invalid-secret')
        with self.assertRaises(ValueError) as error:
            build_outbound(server, 'bad')
        self.assertNotIn('invalid-secret', str(error.exception))
