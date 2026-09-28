from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class Config(_message.Message):
    __slots__ = ("version", "auth", "udp_idle_timeout", "masq_type", "masq_file", "masq_url", "masq_url_rewrite_host", "masq_url_insecure", "masq_string", "masq_string_headers", "masq_string_status_code")
    class MasqStringHeadersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    VERSION_FIELD_NUMBER: _ClassVar[int]
    AUTH_FIELD_NUMBER: _ClassVar[int]
    UDP_IDLE_TIMEOUT_FIELD_NUMBER: _ClassVar[int]
    MASQ_TYPE_FIELD_NUMBER: _ClassVar[int]
    MASQ_FILE_FIELD_NUMBER: _ClassVar[int]
    MASQ_URL_FIELD_NUMBER: _ClassVar[int]
    MASQ_URL_REWRITE_HOST_FIELD_NUMBER: _ClassVar[int]
    MASQ_URL_INSECURE_FIELD_NUMBER: _ClassVar[int]
    MASQ_STRING_FIELD_NUMBER: _ClassVar[int]
    MASQ_STRING_HEADERS_FIELD_NUMBER: _ClassVar[int]
    MASQ_STRING_STATUS_CODE_FIELD_NUMBER: _ClassVar[int]
    version: int
    auth: str
    udp_idle_timeout: int
    masq_type: str
    masq_file: str
    masq_url: str
    masq_url_rewrite_host: bool
    masq_url_insecure: bool
    masq_string: str
    masq_string_headers: _containers.ScalarMap[str, str]
    masq_string_status_code: int
    def __init__(self, version: _Optional[int] = ..., auth: _Optional[str] = ..., udp_idle_timeout: _Optional[int] = ..., masq_type: _Optional[str] = ..., masq_file: _Optional[str] = ..., masq_url: _Optional[str] = ..., masq_url_rewrite_host: bool = ..., masq_url_insecure: bool = ..., masq_string: _Optional[str] = ..., masq_string_headers: _Optional[_Mapping[str, str]] = ..., masq_string_status_code: _Optional[int] = ...) -> None: ...
