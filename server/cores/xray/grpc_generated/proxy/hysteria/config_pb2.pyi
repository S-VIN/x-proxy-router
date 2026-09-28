from server.cores.xray.grpc_generated.common.protocol import server_spec_pb2 as _server_spec_pb2
from server.cores.xray.grpc_generated.common.protocol import user_pb2 as _user_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ClientConfig(_message.Message):
    __slots__ = ("version", "server")
    VERSION_FIELD_NUMBER: _ClassVar[int]
    SERVER_FIELD_NUMBER: _ClassVar[int]
    version: int
    server: _server_spec_pb2.ServerEndpoint
    def __init__(self, version: _Optional[int] = ..., server: _Optional[_Union[_server_spec_pb2.ServerEndpoint, _Mapping]] = ...) -> None: ...

class ServerConfig(_message.Message):
    __slots__ = ("users",)
    USERS_FIELD_NUMBER: _ClassVar[int]
    users: _containers.RepeatedCompositeFieldContainer[_user_pb2.User]
    def __init__(self, users: _Optional[_Iterable[_Union[_user_pb2.User, _Mapping]]] = ...) -> None: ...
