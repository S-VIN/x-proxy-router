from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Config(_message.Message):
    __slots__ = ("host", "path", "header", "accept_proxy_protocol", "ed")
    class HeaderEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    HOST_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    HEADER_FIELD_NUMBER: _ClassVar[int]
    ACCEPT_PROXY_PROTOCOL_FIELD_NUMBER: _ClassVar[int]
    ED_FIELD_NUMBER: _ClassVar[int]
    host: str
    path: str
    header: _containers.ScalarMap[str, str]
    accept_proxy_protocol: bool
    ed: int
    def __init__(self, host: _Optional[str] = ..., path: _Optional[str] = ..., header: _Optional[_Mapping[str, str]] = ..., accept_proxy_protocol: bool = ..., ed: _Optional[int] = ...) -> None: ...
