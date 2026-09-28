from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Config(_message.Message):
    __slots__ = ("show", "dest", "type", "xver", "server_names", "private_key", "min_client_ver", "max_client_ver", "max_time_diff", "short_ids", "mldsa65_seed", "limit_fallback_upload", "limit_fallback_download", "Fingerprint", "server_name", "public_key", "short_id", "mldsa65_verify", "spider_x", "spider_y", "master_key_log")
    SHOW_FIELD_NUMBER: _ClassVar[int]
    DEST_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    XVER_FIELD_NUMBER: _ClassVar[int]
    SERVER_NAMES_FIELD_NUMBER: _ClassVar[int]
    PRIVATE_KEY_FIELD_NUMBER: _ClassVar[int]
    MIN_CLIENT_VER_FIELD_NUMBER: _ClassVar[int]
    MAX_CLIENT_VER_FIELD_NUMBER: _ClassVar[int]
    MAX_TIME_DIFF_FIELD_NUMBER: _ClassVar[int]
    SHORT_IDS_FIELD_NUMBER: _ClassVar[int]
    MLDSA65_SEED_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FALLBACK_UPLOAD_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FALLBACK_DOWNLOAD_FIELD_NUMBER: _ClassVar[int]
    FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    SERVER_NAME_FIELD_NUMBER: _ClassVar[int]
    PUBLIC_KEY_FIELD_NUMBER: _ClassVar[int]
    SHORT_ID_FIELD_NUMBER: _ClassVar[int]
    MLDSA65_VERIFY_FIELD_NUMBER: _ClassVar[int]
    SPIDER_X_FIELD_NUMBER: _ClassVar[int]
    SPIDER_Y_FIELD_NUMBER: _ClassVar[int]
    MASTER_KEY_LOG_FIELD_NUMBER: _ClassVar[int]
    show: bool
    dest: str
    type: str
    xver: int
    server_names: _containers.RepeatedScalarFieldContainer[str]
    private_key: bytes
    min_client_ver: bytes
    max_client_ver: bytes
    max_time_diff: int
    short_ids: _containers.RepeatedScalarFieldContainer[bytes]
    mldsa65_seed: bytes
    limit_fallback_upload: LimitFallback
    limit_fallback_download: LimitFallback
    Fingerprint: str
    server_name: str
    public_key: bytes
    short_id: bytes
    mldsa65_verify: bytes
    spider_x: str
    spider_y: _containers.RepeatedScalarFieldContainer[int]
    master_key_log: str
    def __init__(self, show: bool = ..., dest: _Optional[str] = ..., type: _Optional[str] = ..., xver: _Optional[int] = ..., server_names: _Optional[_Iterable[str]] = ..., private_key: _Optional[bytes] = ..., min_client_ver: _Optional[bytes] = ..., max_client_ver: _Optional[bytes] = ..., max_time_diff: _Optional[int] = ..., short_ids: _Optional[_Iterable[bytes]] = ..., mldsa65_seed: _Optional[bytes] = ..., limit_fallback_upload: _Optional[_Union[LimitFallback, _Mapping]] = ..., limit_fallback_download: _Optional[_Union[LimitFallback, _Mapping]] = ..., Fingerprint: _Optional[str] = ..., server_name: _Optional[str] = ..., public_key: _Optional[bytes] = ..., short_id: _Optional[bytes] = ..., mldsa65_verify: _Optional[bytes] = ..., spider_x: _Optional[str] = ..., spider_y: _Optional[_Iterable[int]] = ..., master_key_log: _Optional[str] = ...) -> None: ...

class LimitFallback(_message.Message):
    __slots__ = ("after_bytes", "bytes_per_sec", "burst_bytes_per_sec")
    AFTER_BYTES_FIELD_NUMBER: _ClassVar[int]
    BYTES_PER_SEC_FIELD_NUMBER: _ClassVar[int]
    BURST_BYTES_PER_SEC_FIELD_NUMBER: _ClassVar[int]
    after_bytes: int
    bytes_per_sec: int
    burst_bytes_per_sec: int
    def __init__(self, after_bytes: _Optional[int] = ..., bytes_per_sec: _Optional[int] = ..., burst_bytes_per_sec: _Optional[int] = ...) -> None: ...
