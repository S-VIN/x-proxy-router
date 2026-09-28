from server.cores.xray.grpc_generated.common.protocol import server_spec_pb2 as _server_spec_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Config(_message.Message):
    __slots__ = ("vnext",)
    VNEXT_FIELD_NUMBER: _ClassVar[int]
    vnext: _server_spec_pb2.ServerEndpoint
    def __init__(self, vnext: _Optional[_Union[_server_spec_pb2.ServerEndpoint, _Mapping]] = ...) -> None: ...
