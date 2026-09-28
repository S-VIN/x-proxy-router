from server.cores.xray.grpc_generated.common.serial import typed_message_pb2 as _typed_message_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Config(_message.Message):
    __slots__ = ("inbound", "outbound", "app", "extension")
    INBOUND_FIELD_NUMBER: _ClassVar[int]
    OUTBOUND_FIELD_NUMBER: _ClassVar[int]
    APP_FIELD_NUMBER: _ClassVar[int]
    EXTENSION_FIELD_NUMBER: _ClassVar[int]
    inbound: _containers.RepeatedCompositeFieldContainer[InboundHandlerConfig]
    outbound: _containers.RepeatedCompositeFieldContainer[OutboundHandlerConfig]
    app: _containers.RepeatedCompositeFieldContainer[_typed_message_pb2.TypedMessage]
    extension: _containers.RepeatedCompositeFieldContainer[_typed_message_pb2.TypedMessage]
    def __init__(self, inbound: _Optional[_Iterable[_Union[InboundHandlerConfig, _Mapping]]] = ..., outbound: _Optional[_Iterable[_Union[OutboundHandlerConfig, _Mapping]]] = ..., app: _Optional[_Iterable[_Union[_typed_message_pb2.TypedMessage, _Mapping]]] = ..., extension: _Optional[_Iterable[_Union[_typed_message_pb2.TypedMessage, _Mapping]]] = ...) -> None: ...

class InboundHandlerConfig(_message.Message):
    __slots__ = ("tag", "receiver_settings", "proxy_settings")
    TAG_FIELD_NUMBER: _ClassVar[int]
    RECEIVER_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    PROXY_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    tag: str
    receiver_settings: _typed_message_pb2.TypedMessage
    proxy_settings: _typed_message_pb2.TypedMessage
    def __init__(self, tag: _Optional[str] = ..., receiver_settings: _Optional[_Union[_typed_message_pb2.TypedMessage, _Mapping]] = ..., proxy_settings: _Optional[_Union[_typed_message_pb2.TypedMessage, _Mapping]] = ...) -> None: ...

class OutboundHandlerConfig(_message.Message):
    __slots__ = ("tag", "sender_settings", "proxy_settings", "expire", "comment")
    TAG_FIELD_NUMBER: _ClassVar[int]
    SENDER_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    PROXY_SETTINGS_FIELD_NUMBER: _ClassVar[int]
    EXPIRE_FIELD_NUMBER: _ClassVar[int]
    COMMENT_FIELD_NUMBER: _ClassVar[int]
    tag: str
    sender_settings: _typed_message_pb2.TypedMessage
    proxy_settings: _typed_message_pb2.TypedMessage
    expire: int
    comment: str
    def __init__(self, tag: _Optional[str] = ..., sender_settings: _Optional[_Union[_typed_message_pb2.TypedMessage, _Mapping]] = ..., proxy_settings: _Optional[_Union[_typed_message_pb2.TypedMessage, _Mapping]] = ..., expire: _Optional[int] = ..., comment: _Optional[str] = ...) -> None: ...
