from server.cores.xray.grpc_generated.common.protocol import user_pb2 as _user_pb2
from server.cores.xray.grpc_generated.common.serial import typed_message_pb2 as _typed_message_pb2
from server.cores.xray.grpc_generated.core import config_pb2 as _config_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AddUserOperation(_message.Message):
    __slots__ = ("user",)
    USER_FIELD_NUMBER: _ClassVar[int]
    user: _user_pb2.User
    def __init__(self, user: _Optional[_Union[_user_pb2.User, _Mapping]] = ...) -> None: ...

class RemoveUserOperation(_message.Message):
    __slots__ = ("email",)
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    email: str
    def __init__(self, email: _Optional[str] = ...) -> None: ...

class AddInboundRequest(_message.Message):
    __slots__ = ("inbound",)
    INBOUND_FIELD_NUMBER: _ClassVar[int]
    inbound: _config_pb2.InboundHandlerConfig
    def __init__(self, inbound: _Optional[_Union[_config_pb2.InboundHandlerConfig, _Mapping]] = ...) -> None: ...

class AddInboundResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RemoveInboundRequest(_message.Message):
    __slots__ = ("tag",)
    TAG_FIELD_NUMBER: _ClassVar[int]
    tag: str
    def __init__(self, tag: _Optional[str] = ...) -> None: ...

class RemoveInboundResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AlterInboundRequest(_message.Message):
    __slots__ = ("tag", "operation")
    TAG_FIELD_NUMBER: _ClassVar[int]
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    tag: str
    operation: _typed_message_pb2.TypedMessage
    def __init__(self, tag: _Optional[str] = ..., operation: _Optional[_Union[_typed_message_pb2.TypedMessage, _Mapping]] = ...) -> None: ...

class AlterInboundResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListInboundsRequest(_message.Message):
    __slots__ = ("isOnlyTags",)
    ISONLYTAGS_FIELD_NUMBER: _ClassVar[int]
    isOnlyTags: bool
    def __init__(self, isOnlyTags: bool = ...) -> None: ...

class ListInboundsResponse(_message.Message):
    __slots__ = ("inbounds",)
    INBOUNDS_FIELD_NUMBER: _ClassVar[int]
    inbounds: _containers.RepeatedCompositeFieldContainer[_config_pb2.InboundHandlerConfig]
    def __init__(self, inbounds: _Optional[_Iterable[_Union[_config_pb2.InboundHandlerConfig, _Mapping]]] = ...) -> None: ...

class GetInboundUserRequest(_message.Message):
    __slots__ = ("tag", "email")
    TAG_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    tag: str
    email: str
    def __init__(self, tag: _Optional[str] = ..., email: _Optional[str] = ...) -> None: ...

class GetInboundUserResponse(_message.Message):
    __slots__ = ("users",)
    USERS_FIELD_NUMBER: _ClassVar[int]
    users: _containers.RepeatedCompositeFieldContainer[_user_pb2.User]
    def __init__(self, users: _Optional[_Iterable[_Union[_user_pb2.User, _Mapping]]] = ...) -> None: ...

class GetInboundUsersCountResponse(_message.Message):
    __slots__ = ("count",)
    COUNT_FIELD_NUMBER: _ClassVar[int]
    count: int
    def __init__(self, count: _Optional[int] = ...) -> None: ...

class AddOutboundRequest(_message.Message):
    __slots__ = ("outbound",)
    OUTBOUND_FIELD_NUMBER: _ClassVar[int]
    outbound: _config_pb2.OutboundHandlerConfig
    def __init__(self, outbound: _Optional[_Union[_config_pb2.OutboundHandlerConfig, _Mapping]] = ...) -> None: ...

class AddOutboundResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RemoveOutboundRequest(_message.Message):
    __slots__ = ("tag",)
    TAG_FIELD_NUMBER: _ClassVar[int]
    tag: str
    def __init__(self, tag: _Optional[str] = ...) -> None: ...

class RemoveOutboundResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AlterOutboundRequest(_message.Message):
    __slots__ = ("tag", "operation")
    TAG_FIELD_NUMBER: _ClassVar[int]
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    tag: str
    operation: _typed_message_pb2.TypedMessage
    def __init__(self, tag: _Optional[str] = ..., operation: _Optional[_Union[_typed_message_pb2.TypedMessage, _Mapping]] = ...) -> None: ...

class AlterOutboundResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListOutboundsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListOutboundsResponse(_message.Message):
    __slots__ = ("outbounds",)
    OUTBOUNDS_FIELD_NUMBER: _ClassVar[int]
    outbounds: _containers.RepeatedCompositeFieldContainer[_config_pb2.OutboundHandlerConfig]
    def __init__(self, outbounds: _Optional[_Iterable[_Union[_config_pb2.OutboundHandlerConfig, _Mapping]]] = ...) -> None: ...

class Config(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
