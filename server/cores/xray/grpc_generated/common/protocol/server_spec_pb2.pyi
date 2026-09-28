from server.cores.xray.grpc_generated.common.net import address_pb2 as _address_pb2
from server.cores.xray.grpc_generated.common.protocol import user_pb2 as _user_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ServerEndpoint(_message.Message):
    __slots__ = ("address", "port", "user")
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    PORT_FIELD_NUMBER: _ClassVar[int]
    USER_FIELD_NUMBER: _ClassVar[int]
    address: _address_pb2.IPOrDomain
    port: int
    user: _user_pb2.User
    def __init__(self, address: _Optional[_Union[_address_pb2.IPOrDomain, _Mapping]] = ..., port: _Optional[int] = ..., user: _Optional[_Union[_user_pb2.User, _Mapping]] = ...) -> None: ...
