"""Build Xray outbound protobufs in memory (Xray 26.3.27 schema)."""

import base64
from copy import deepcopy
from ipaddress import ip_address
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from google.protobuf.json_format import ParseDict, ParseError

from ...models import OutboundServer
from .outbound_config import outbound_config
from .xray_grpc_client import typed_message
from .grpc_generated.app.proxyman.config_pb2 import SenderConfig
from .grpc_generated.common.net.address_pb2 import IPOrDomain
from .grpc_generated.common.protocol.server_spec_pb2 import ServerEndpoint
from .grpc_generated.common.protocol.user_pb2 import User
from .grpc_generated.core.config_pb2 import OutboundHandlerConfig
from .grpc_generated.proxy.vless.account_pb2 import Account
from .grpc_generated.proxy.vless.outbound.config_pb2 import Config as VlessConfig
from .grpc_generated.proxy.shadowsocks import config_pb2 as ss
from .grpc_generated.proxy.shadowsocks_2022.config_pb2 import ClientConfig as Shadowsocks2022
from .grpc_generated.proxy.hysteria.config_pb2 import ClientConfig as HysteriaClient
from .grpc_generated.transport.internet import config_pb2 as internet
from .grpc_generated.transport.internet.tcp.config_pb2 import Config as TcpConfig
from .grpc_generated.transport.internet.tls.config_pb2 import Config as TlsConfig
from .grpc_generated.transport.internet.reality.config_pb2 import Config as RealityConfig
from .grpc_generated.transport.internet.websocket.config_pb2 import Config as WsConfig
from .grpc_generated.transport.internet.grpc.config_pb2 import Config as GrpcConfig
from .grpc_generated.transport.internet.splithttp.config_pb2 import Config as XhttpConfig
from .grpc_generated.transport.internet.hysteria.config_pb2 import Config as HysteriaConfig


def _address(value):
    try:
        return IPOrDomain(ip=ip_address(value).packed)
    except ValueError:
        if not value:
            raise ValueError("Server address is required") from None
        return IPOrDomain(domain=value)


def _message(cls, data, aliases=None):
    """Map known JSON option names to protobuf names; never ignore unknown fields."""
    fields = cls.DESCRIPTOR.fields
    names = {f.name.replace('_', '').lower(): f.name for f in fields}
    mapped = {}
    for key, value in data.items():
        name = (aliases or {}).get(key, names.get(key.replace('_', '').lower()))
        if name is None:
            raise ValueError(f"Unsupported {cls.DESCRIPTOR.full_name} option: {key}")
        mapped[name] = value
    try:
        return ParseDict(mapped, cls())
    except (ParseError, ValueError, TypeError):
        raise ValueError(f"Invalid {cls.DESCRIPTOR.full_name} options") from None


def _range(value=0):
    parts = str(value).split('-')
    low, high = int(parts[0]), int(parts[-1])
    if len(parts) > 2 or low < 0 or low > high:
        raise ValueError("Invalid range")
    return {"from": low, "to": high}


def _decode(value, lengths):
    try:
        result = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        if len(result) in lengths:
            return result
    except (ValueError, TypeError):
        pass
    raise ValueError("Invalid encoded key length or encoding")


def _reality(options):
    options = deepcopy(options)
    key = options.pop('password', None) or options.pop('publicKey', '')
    options.pop('publicKey', None)
    short = options.pop('shortId', '')
    if len(short) > 16 or len(short) % 2:
        raise ValueError("Invalid Reality short ID")
    try:
        short_bytes = bytes.fromhex(short).ljust(8, b'\0')
    except ValueError:
        raise ValueError("Invalid Reality short ID") from None
    spider = options.pop('spiderX', '') or '/'
    if not spider.startswith('/'):
        raise ValueError("Reality spiderX must start with /")
    url = urlsplit(spider)
    query = dict(parse_qsl(url.query))
    ranges = []
    for name in ('p', 'c', 't', 'i', 'r'):
        pair = _range(query.pop(name, 0))
        ranges.extend(pair.values())
    result = _message(RealityConfig, options, {'fingerprint': 'Fingerprint'})
    result.public_key = _decode(key, (32,))
    result.short_id = short_bytes
    result.spider_x = urlunsplit(url._replace(query=urlencode(sorted(query.items()))))
    result.spider_y.extend(ranges)
    return result


def _xhttp(options):
    options = deepcopy(options)
    extra = options.pop('extra', None)
    if extra is not None:
        options = {**extra, **{k: options.get(k, '') for k in ('host', 'path', 'mode')}}
    defaults = dict(mode='auto', xPaddingKey='x_padding', xPaddingHeader='X-Padding',
                    xPaddingPlacement='queryInHeader', xPaddingMethod='repeat-x',
                    uplinkHTTPMethod='POST', sessionPlacement='path', seqPlacement='path',
                    uplinkDataPlacement='auto')
    for key, value in defaults.items():
        if not options.get(key):
            options[key] = value
    if options['mode'] not in ('auto', 'stream-one', 'stream-up', 'packet-up'):
        raise ValueError("Invalid XHTTP mode")
    for prefix, default in (('session', 'session'), ('seq', 'seq'), ('uplinkData', 'data')):
        placement = options[prefix + 'Placement']
        if not options.get(prefix + 'Key') and placement not in ('path', 'body'):
            options[prefix + 'Key'] = ('X-' + default.title() if placement in ('header', 'auto') else 'x_' + default)
    for key in ('xPaddingBytes', 'scMaxEachPostBytes', 'scMinPostsIntervalMs', 'scStreamUpServerSecs', 'uplinkChunkSize'):
        options[key] = _range(options.get(key, 0))
    xmux = options.setdefault('xmux', {})
    if not any(xmux.values()):
        xmux.update(maxConcurrency=1, hMaxRequestTimes='600-900', hMaxReusableSecs='1800-3000')
    for key in ('maxConcurrency', 'maxConnections', 'cMaxReuseTimes', 'hMaxRequestTimes', 'hMaxReusableSecs'):
        xmux[key] = _range(xmux.get(key, 0))
    if xmux['maxConcurrency']['to'] and xmux['maxConnections']['to']:
        raise ValueError("XHTTP maxConcurrency and maxConnections are mutually exclusive")
    download = options.pop('downloadSettings', None)
    result = _message(XhttpConfig, options)
    if download is not None:
        if result.mode == 'stream-one':
            raise ValueError("XHTTP stream-one cannot have downloadSettings")
        result.downloadSettings.CopyFrom(_stream(download))
    return result


def _quic(options):
    options = deepcopy(options)
    for key in ('brutalUp', 'brutalDown'):
        if key in options:
            match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]?)(?:b(?:ps)?)?\s*", str(options[key]).lower())
            if not match:
                raise ValueError("Invalid QUIC bandwidth")
            options[key] = int(float(match[1]) * 1024 ** ('', 'k', 'm', 'g', 't').index(match[2])) // 8
    hop = options.pop('udpHop', {})
    ports = []
    raw_ports = hop.get('ports', '')
    if raw_ports:
        for part in str(raw_ports).split(','):
            pair = _range(part)
            if not 1 <= pair['from'] <= pair['to'] <= 65535:
                raise ValueError("Invalid UDP hop port")
            ports.extend(range(pair['from'], pair['to'] + 1))
    if set(hop) - {'ports', 'interval'}:
        raise ValueError("Unsupported UDP hop options")
    interval = _range(hop.get('interval', 0))
    result = _message(internet.QuicParams, options, {
        'initConnectionReceiveWindow': 'init_conn_receive_window',
        'maxConnectionReceiveWindow': 'max_conn_receive_window'})
    result.udp_hop.CopyFrom(internet.UdpHop(ports=ports,
        interval_min=interval['from'], interval_max=interval['to']))
    return result


def _stream(data):
    data = deepcopy(data)
    network = data.pop('network', 'tcp')
    protocol = {'raw': 'tcp', 'ws': 'websocket', 'xhttp': 'splithttp'}.get(network, network)
    result = internet.StreamConfig(protocol_name=protocol)
    security = data.pop('security', 'none')
    if 'address' in data:
        result.address.CopyFrom(_address(data.pop('address')))
    result.port = data.pop('port', 0)
    if security == 'tls':
        options = data.pop('tlsSettings', {})
        config = _message(TlsConfig, options, {'alpn': 'next_protocol'})
    elif security == 'reality':
        if protocol not in ('tcp', 'grpc', 'splithttp'):
            raise ValueError("Reality requires TCP, gRPC or XHTTP")
        config = _reality(data.pop('realitySettings', {}))
    elif security not in ('none', ''):
        raise ValueError("Unsupported stream security")
    if security not in ('none', ''):
        packed = typed_message(config)
        result.security_type = packed.type
        result.security_settings.append(packed)
    transports = {'tcpSettings': ('tcp', TcpConfig), 'rawSettings': ('tcp', TcpConfig),
                  'wsSettings': ('websocket', WsConfig), 'grpcSettings': ('grpc', GrpcConfig),
                  'xhttpSettings': ('splithttp', XhttpConfig),
                  'hysteriaSettings': ('hysteria', HysteriaConfig)}
    for key, (name, cls) in transports.items():
        if key not in data:
            continue
        options = data.pop(key)
        if name == 'splithttp':
            config = _xhttp(options)
        elif name == 'websocket':
            options = deepcopy(options)
            headers = options.pop('headers', {})
            for header in list(headers):
                if header.lower() == 'host':
                    options.setdefault('host', headers.pop(header))
            options['header'] = headers
            url = urlsplit(options.get('path', ''))
            query = dict(parse_qsl(url.query, keep_blank_values=True))
            if 'ed' in query:
                options['ed'] = int(query.pop('ed'))
                options['path'] = urlunsplit(url._replace(query=urlencode(sorted(query.items()))))
            config = _message(cls, options)
        else:
            config = _message(cls, options)
            if name == 'hysteria':
                if config.version != 2:
                    raise ValueError('Hysteria requires version 2')
                if config.udp_idle_timeout == 0:
                    config.udp_idle_timeout = 60
        result.transport_settings.append(internet.TransportConfig(protocol_name=name, settings=typed_message(config)))
    if 'sockopt' in data:
        result.socket_settings.CopyFrom(_message(internet.SocketConfig, data.pop('sockopt')))
    if 'finalmask' in data:
        mask = data.pop('finalmask')
        if set(mask) - {'quicParams'}:
            raise ValueError("TCP/UDP finalmask is not yet supported")
        if 'quicParams' in mask:
            result.quic_params.CopyFrom(_quic(mask['quicParams']))
    if data:
        raise ValueError('Unsupported stream options: ' + ', '.join(data))
    return result


def build_outbound(server: OutboundServer, tag: str) -> OutboundHandlerConfig:
    if type(server.port) is not int or not 1 <= server.port <= 65535:
        raise ValueError("Invalid outbound port")
    data = outbound_config(server, tag)
    endpoint = ServerEndpoint(address=_address(server.address), port=server.port)
    settings = data['settings']
    if data['protocol'] == 'vless':
        options = settings['vnext'][0]['users'][0]
        user = User(level=options.pop('level', 0), email=options.pop('email', ''))
        account = _message(Account, options)
        if account.encryption != 'none':
            parts = account.encryption.split('.')
            if len(parts) < 4 or parts[0] != 'mlkem768x25519plus' or parts[1] not in ('native', 'xorpub', 'random') or parts[2] not in ('0rtt', '1rtt'):
                raise ValueError("Unsupported VLESS encryption")
            account.xorMode = ('native', 'xorpub', 'random').index(parts[1])
            account.seconds = int(parts[2] == '0rtt')
            padding = []
            keys = []
            for part in parts[3:]:
                if len(part) < 20:
                    padding.append(part)
                else:
                    _decode(part, (32, 1184))
                    keys.append(part)
            if not keys:
                raise ValueError("VLESS encryption requires a key")
            account.padding, account.encryption = '.'.join(padding), '.'.join(keys)
        user.account.CopyFrom(typed_message(account))
        endpoint.user.CopyFrom(user)
        config = VlessConfig(vnext=endpoint)
    elif data['protocol'] == 'shadowsocks':
        options = settings['servers'][0]
        method = options['method']
        if not options['password']:
            raise ValueError("Shadowsocks password is required")
        if method.startswith('2022-'):
            config = Shadowsocks2022(address=endpoint.address, port=endpoint.port,
                method=method, key=options['password'], udp_over_tcp=options['uot'],
                udp_over_tcp_version=options.get('uotVersion', 0))
        else:
            if options['uot']:
                raise ValueError("This Xray version supports Shadowsocks UoT only with 2022 methods")
            cipher = {'none': ss.NONE, 'aes-128-gcm': ss.AES_128_GCM, 'aes-256-gcm': ss.AES_256_GCM,
                      'chacha20-ietf-poly1305': ss.CHACHA20_POLY1305,
                      'xchacha20-ietf-poly1305': ss.XCHACHA20_POLY1305}[method]
            endpoint.user.CopyFrom(User(level=options.get('level', 0), email=options.get('email', ''),
                account=typed_message(ss.Account(password=options['password'], cipher_type=cipher))))
            config = ss.ClientConfig(server=endpoint)
        unknown = set(options) - {'address', 'port', 'password', 'method', 'uot', 'uotVersion', 'level', 'email'}
        if unknown:
            raise ValueError('Unsupported Shadowsocks options: ' + ', '.join(unknown))
    elif data['protocol'] == 'hysteria':
        if set(settings) - {'address', 'port', 'version'}:
            raise ValueError("Unsupported Hysteria proxy options")
        config = HysteriaClient(version=2, server=endpoint)
    else:
        raise ValueError("Unsupported outbound protocol")
    return OutboundHandlerConfig(tag=tag, proxy_settings=typed_message(config),
        sender_settings=typed_message(SenderConfig(stream_settings=_stream(data['streamSettings']))))
