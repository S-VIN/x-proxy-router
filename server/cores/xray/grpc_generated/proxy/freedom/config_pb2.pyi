from server.cores.xray.grpc_generated.common.protocol import server_spec_pb2 as _server_spec_pb2
from server.cores.xray.grpc_generated.transport.internet import config_pb2 as _config_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DestinationOverride(_message.Message):
    __slots__ = ("server",)
    SERVER_FIELD_NUMBER: _ClassVar[int]
    server: _server_spec_pb2.ServerEndpoint
    def __init__(self, server: _Optional[_Union[_server_spec_pb2.ServerEndpoint, _Mapping]] = ...) -> None: ...

class Fragment(_message.Message):
    __slots__ = ("packets_from", "packets_to", "length_min", "length_max", "interval_min", "interval_max", "max_split_min", "max_split_max")
    PACKETS_FROM_FIELD_NUMBER: _ClassVar[int]
    PACKETS_TO_FIELD_NUMBER: _ClassVar[int]
    LENGTH_MIN_FIELD_NUMBER: _ClassVar[int]
    LENGTH_MAX_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_MIN_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_MAX_FIELD_NUMBER: _ClassVar[int]
    MAX_SPLIT_MIN_FIELD_NUMBER: _ClassVar[int]
    MAX_SPLIT_MAX_FIELD_NUMBER: _ClassVar[int]
    packets_from: int
    packets_to: int
    length_min: int
    length_max: int
    interval_min: int
    interval_max: int
    max_split_min: int
    max_split_max: int
    def __init__(self, packets_from: _Optional[int] = ..., packets_to: _Optional[int] = ..., length_min: _Optional[int] = ..., length_max: _Optional[int] = ..., interval_min: _Optional[int] = ..., interval_max: _Optional[int] = ..., max_split_min: _Optional[int] = ..., max_split_max: _Optional[int] = ...) -> None: ...

class Noise(_message.Message):
    __slots__ = ("length_min", "length_max", "delay_min", "delay_max", "packet", "apply_to")
    LENGTH_MIN_FIELD_NUMBER: _ClassVar[int]
    LENGTH_MAX_FIELD_NUMBER: _ClassVar[int]
    DELAY_MIN_FIELD_NUMBER: _ClassVar[int]
    DELAY_MAX_FIELD_NUMBER: _ClassVar[int]
    PACKET_FIELD_NUMBER: _ClassVar[int]
    APPLY_TO_FIELD_NUMBER: _ClassVar[int]
    length_min: int
    length_max: int
    delay_min: int
    delay_max: int
    packet: bytes
    apply_to: str
    def __init__(self, length_min: _Optional[int] = ..., length_max: _Optional[int] = ..., delay_min: _Optional[int] = ..., delay_max: _Optional[int] = ..., packet: _Optional[bytes] = ..., apply_to: _Optional[str] = ...) -> None: ...

class Config(_message.Message):
    __slots__ = ("domain_strategy", "destination_override", "user_level", "fragment", "proxy_protocol", "noises")
    DOMAIN_STRATEGY_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_OVERRIDE_FIELD_NUMBER: _ClassVar[int]
    USER_LEVEL_FIELD_NUMBER: _ClassVar[int]
    FRAGMENT_FIELD_NUMBER: _ClassVar[int]
    PROXY_PROTOCOL_FIELD_NUMBER: _ClassVar[int]
    NOISES_FIELD_NUMBER: _ClassVar[int]
    domain_strategy: _config_pb2.DomainStrategy
    destination_override: DestinationOverride
    user_level: int
    fragment: Fragment
    proxy_protocol: int
    noises: _containers.RepeatedCompositeFieldContainer[Noise]
    def __init__(self, domain_strategy: _Optional[_Union[_config_pb2.DomainStrategy, str]] = ..., destination_override: _Optional[_Union[DestinationOverride, _Mapping]] = ..., user_level: _Optional[int] = ..., fragment: _Optional[_Union[Fragment, _Mapping]] = ..., proxy_protocol: _Optional[int] = ..., noises: _Optional[_Iterable[_Union[Noise, _Mapping]]] = ...) -> None: ...
