from server.cores.xray.grpc_generated.app.proxyman import config_pb2 as _config_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Reverse(_message.Message):
    __slots__ = ("tag", "sniffing")
    TAG_FIELD_NUMBER: _ClassVar[int]
    SNIFFING_FIELD_NUMBER: _ClassVar[int]
    tag: str
    sniffing: _config_pb2.SniffingConfig
    def __init__(self, tag: _Optional[str] = ..., sniffing: _Optional[_Union[_config_pb2.SniffingConfig, _Mapping]] = ...) -> None: ...

class Account(_message.Message):
    __slots__ = ("id", "flow", "encryption", "xorMode", "seconds", "padding", "reverse", "testpre", "testseed")
    ID_FIELD_NUMBER: _ClassVar[int]
    FLOW_FIELD_NUMBER: _ClassVar[int]
    ENCRYPTION_FIELD_NUMBER: _ClassVar[int]
    XORMODE_FIELD_NUMBER: _ClassVar[int]
    SECONDS_FIELD_NUMBER: _ClassVar[int]
    PADDING_FIELD_NUMBER: _ClassVar[int]
    REVERSE_FIELD_NUMBER: _ClassVar[int]
    TESTPRE_FIELD_NUMBER: _ClassVar[int]
    TESTSEED_FIELD_NUMBER: _ClassVar[int]
    id: str
    flow: str
    encryption: str
    xorMode: int
    seconds: int
    padding: str
    reverse: Reverse
    testpre: int
    testseed: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, id: _Optional[str] = ..., flow: _Optional[str] = ..., encryption: _Optional[str] = ..., xorMode: _Optional[int] = ..., seconds: _Optional[int] = ..., padding: _Optional[str] = ..., reverse: _Optional[_Union[Reverse, _Mapping]] = ..., testpre: _Optional[int] = ..., testseed: _Optional[_Iterable[int]] = ...) -> None: ...
