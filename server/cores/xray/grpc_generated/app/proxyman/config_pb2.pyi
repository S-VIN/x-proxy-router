from server.cores.xray.grpc_generated.common.net import address_pb2 as _address_pb2
from server.cores.xray.grpc_generated.common.net import port_pb2 as _port_pb2
from server.cores.xray.grpc_generated.transport.internet import config_pb2 as _config_pb2
from server.cores.xray.grpc_generated.common.serial import typed_message_pb2 as _typed_message_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class InboundConfig(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SniffingConfig(_message.Message):
    __slots__ = ("enabled", "destination_override", "domains_excluded", "metadata_only", "route_only")
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_OVERRIDE_FIELD_NUMBER: _ClassVar[int]
    DOMAINS_EXCLUDED_FIELD_NUMBER: _ClassVar[int]
    METADATA_ONLY_FIELD_NUMBER: _ClassVar[int]
    ROUTE_ONLY_FIELD_NUMBER: _ClassVar[int]
    enabled: bool
    destination_override: _containers.RepeatedScalarFieldContainer[str]
    domains_excluded: _containers.RepeatedScalarFieldContainer[str]
    metadata_only: bool
    route_only: bool
    def __init__(self, enabled: bool = ..., destination_override: _Optional[_Iterable[str]] = ..., domains_excluded: _Optional[_Iterable[str]] = ..., metadata_only: bool = ..., route_only: bool = ...) -> None: ...

class ReceiverConfig(_message.Message):
    __slots__ = ("port_list", "listen", "stream_settings", "receive_original_destination", "sniffing_settings")
    PORT_LIST_FIELD_NUMBER: _ClassVar[int]
    LISTEN_FIELD_NUMBER: _ClassVar[int]
    STREAM_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    RECEIVE_ORIGINAL_DESTINATION_FIELD_NUMBER: _ClassVar[int]
    SNIFFING_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    port_list: _port_pb2.PortList
    listen: _address_pb2.IPOrDomain
    stream_settings: _config_pb2.StreamConfig
    receive_original_destination: bool
    sniffing_settings: SniffingConfig
    def __init__(self, port_list: _Optional[_Union[_port_pb2.PortList, _Mapping]] = ..., listen: _Optional[_Union[_address_pb2.IPOrDomain, _Mapping]] = ..., stream_settings: _Optional[_Union[_config_pb2.StreamConfig, _Mapping]] = ..., receive_original_destination: bool = ..., sniffing_settings: _Optional[_Union[SniffingConfig, _Mapping]] = ...) -> None: ...

class InboundHandlerConfig(_message.Message):
    __slots__ = ("tag", "receiver_settings", "proxy_settings")
    TAG_FIELD_NUMBER: _ClassVar[int]
    RECEIVER_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    PROXY_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    tag: str
    receiver_settings: _typed_message_pb2.TypedMessage
    proxy_settings: _typed_message_pb2.TypedMessage
    def __init__(self, tag: _Optional[str] = ..., receiver_settings: _Optional[_Union[_typed_message_pb2.TypedMessage, _Mapping]] = ..., proxy_settings: _Optional[_Union[_typed_message_pb2.TypedMessage, _Mapping]] = ...) -> None: ...

class OutboundConfig(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SenderConfig(_message.Message):
    __slots__ = ("via", "stream_settings", "proxy_settings", "multiplex_settings", "via_cidr", "target_strategy")
    VIA_FIELD_NUMBER: _ClassVar[int]
    STREAM_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    PROXY_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    MULTIPLEX_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    VIA_CIDR_FIELD_NUMBER: _ClassVar[int]
    TARGET_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    via: _address_pb2.IPOrDomain
    stream_settings: _config_pb2.StreamConfig
    proxy_settings: _config_pb2.ProxyConfig
    multiplex_settings: MultiplexingConfig
    via_cidr: str
    target_strategy: _config_pb2.DomainStrategy
    def __init__(self, via: _Optional[_Union[_address_pb2.IPOrDomain, _Mapping]] = ..., stream_settings: _Optional[_Union[_config_pb2.StreamConfig, _Mapping]] = ..., proxy_settings: _Optional[_Union[_config_pb2.ProxyConfig, _Mapping]] = ..., multiplex_settings: _Optional[_Union[MultiplexingConfig, _Mapping]] = ..., via_cidr: _Optional[str] = ..., target_strategy: _Optional[_Union[_config_pb2.DomainStrategy, str]] = ...) -> None: ...

class MultiplexingConfig(_message.Message):
    __slots__ = ("enabled", "concurrency", "xudpConcurrency", "xudpProxyUDP443")
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    CONCURRENCY_FIELD_NUMBER: _ClassVar[int]
    XUDPCONCURRENCY_FIELD_NUMBER: _ClassVar[int]
    XUDPPROXYUDP443_FIELD_NUMBER: _ClassVar[int]
    enabled: bool
    concurrency: int
    xudpConcurrency: int
    xudpProxyUDP443: str
    def __init__(self, enabled: bool = ..., concurrency: _Optional[int] = ..., xudpConcurrency: _Optional[int] = ..., xudpProxyUDP443: _Optional[str] = ...) -> None: ...
