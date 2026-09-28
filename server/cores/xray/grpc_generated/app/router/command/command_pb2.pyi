from server.cores.xray.grpc_generated.common.net import network_pb2 as _network_pb2
from server.cores.xray.grpc_generated.common.serial import typed_message_pb2 as _typed_message_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RoutingContext(_message.Message):
    __slots__ = ("InboundTag", "Network", "SourceIPs", "TargetIPs", "SourcePort", "TargetPort", "TargetDomain", "Protocol", "User", "Attributes", "OutboundGroupTags", "OutboundTag", "LocalIPs", "LocalPort", "VlessRoute")
    class AttributesEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    INBOUNDTAG_FIELD_NUMBER: _ClassVar[int]
    NETWORK_FIELD_NUMBER: _ClassVar[int]
    SOURCEIPS_FIELD_NUMBER: _ClassVar[int]
    TARGETIPS_FIELD_NUMBER: _ClassVar[int]
    SOURCEPORT_FIELD_NUMBER: _ClassVar[int]
    TARGETPORT_FIELD_NUMBER: _ClassVar[int]
    TARGETDOMAIN_FIELD_NUMBER: _ClassVar[int]
    PROTOCOL_FIELD_NUMBER: _ClassVar[int]
    USER_FIELD_NUMBER: _ClassVar[int]
    ATTRIBUTES_FIELD_NUMBER: _ClassVar[int]
    OUTBOUNDGROUPTAGS_FIELD_NUMBER: _ClassVar[int]
    OUTBOUNDTAG_FIELD_NUMBER: _ClassVar[int]
    LOCALIPS_FIELD_NUMBER: _ClassVar[int]
    LOCALPORT_FIELD_NUMBER: _ClassVar[int]
    VLESSROUTE_FIELD_NUMBER: _ClassVar[int]
    InboundTag: str
    Network: _network_pb2.Network
    SourceIPs: _containers.RepeatedScalarFieldContainer[bytes]
    TargetIPs: _containers.RepeatedScalarFieldContainer[bytes]
    SourcePort: int
    TargetPort: int
    TargetDomain: str
    Protocol: str
    User: str
    Attributes: _containers.ScalarMap[str, str]
    OutboundGroupTags: _containers.RepeatedScalarFieldContainer[str]
    OutboundTag: str
    LocalIPs: _containers.RepeatedScalarFieldContainer[bytes]
    LocalPort: int
    VlessRoute: int
    def __init__(self, InboundTag: _Optional[str] = ..., Network: _Optional[_Union[_network_pb2.Network, str]] = ..., SourceIPs: _Optional[_Iterable[bytes]] = ..., TargetIPs: _Optional[_Iterable[bytes]] = ..., SourcePort: _Optional[int] = ..., TargetPort: _Optional[int] = ..., TargetDomain: _Optional[str] = ..., Protocol: _Optional[str] = ..., User: _Optional[str] = ..., Attributes: _Optional[_Mapping[str, str]] = ..., OutboundGroupTags: _Optional[_Iterable[str]] = ..., OutboundTag: _Optional[str] = ..., LocalIPs: _Optional[_Iterable[bytes]] = ..., LocalPort: _Optional[int] = ..., VlessRoute: _Optional[int] = ...) -> None: ...

class SubscribeRoutingStatsRequest(_message.Message):
    __slots__ = ("FieldSelectors",)
    FIELDSELECTORS_FIELD_NUMBER: _ClassVar[int]
    FieldSelectors: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, FieldSelectors: _Optional[_Iterable[str]] = ...) -> None: ...

class TestRouteRequest(_message.Message):
    __slots__ = ("RoutingContext", "FieldSelectors", "PublishResult")
    ROUTINGCONTEXT_FIELD_NUMBER: _ClassVar[int]
    FIELDSELECTORS_FIELD_NUMBER: _ClassVar[int]
    PUBLISHRESULT_FIELD_NUMBER: _ClassVar[int]
    RoutingContext: RoutingContext
    FieldSelectors: _containers.RepeatedScalarFieldContainer[str]
    PublishResult: bool
    def __init__(self, RoutingContext: _Optional[_Union[RoutingContext, _Mapping]] = ..., FieldSelectors: _Optional[_Iterable[str]] = ..., PublishResult: bool = ...) -> None: ...

class PrincipleTargetInfo(_message.Message):
    __slots__ = ("tag",)
    TAG_FIELD_NUMBER: _ClassVar[int]
    tag: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, tag: _Optional[_Iterable[str]] = ...) -> None: ...

class OverrideInfo(_message.Message):
    __slots__ = ("target",)
    TARGET_FIELD_NUMBER: _ClassVar[int]
    target: str
    def __init__(self, target: _Optional[str] = ...) -> None: ...

class BalancerMsg(_message.Message):
    __slots__ = ("override", "principle_target")
    OVERRIDE_FIELD_NUMBER: _ClassVar[int]
    PRINCIPLE_TARGET_FIELD_NUMBER: _ClassVar[int]
    override: OverrideInfo
    principle_target: PrincipleTargetInfo
    def __init__(self, override: _Optional[_Union[OverrideInfo, _Mapping]] = ..., principle_target: _Optional[_Union[PrincipleTargetInfo, _Mapping]] = ...) -> None: ...

class GetBalancerInfoRequest(_message.Message):
    __slots__ = ("tag",)
    TAG_FIELD_NUMBER: _ClassVar[int]
    tag: str
    def __init__(self, tag: _Optional[str] = ...) -> None: ...

class GetBalancerInfoResponse(_message.Message):
    __slots__ = ("balancer",)
    BALANCER_FIELD_NUMBER: _ClassVar[int]
    balancer: BalancerMsg
    def __init__(self, balancer: _Optional[_Union[BalancerMsg, _Mapping]] = ...) -> None: ...

class OverrideBalancerTargetRequest(_message.Message):
    __slots__ = ("balancerTag", "target")
    BALANCERTAG_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    balancerTag: str
    target: str
    def __init__(self, balancerTag: _Optional[str] = ..., target: _Optional[str] = ...) -> None: ...

class OverrideBalancerTargetResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class AddRuleRequest(_message.Message):
    __slots__ = ("config", "shouldAppend")
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    SHOULDAPPEND_FIELD_NUMBER: _ClassVar[int]
    config: _typed_message_pb2.TypedMessage
    shouldAppend: bool
    def __init__(self, config: _Optional[_Union[_typed_message_pb2.TypedMessage, _Mapping]] = ..., shouldAppend: bool = ...) -> None: ...

class AddRuleResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RemoveRuleRequest(_message.Message):
    __slots__ = ("ruleTag",)
    RULETAG_FIELD_NUMBER: _ClassVar[int]
    ruleTag: str
    def __init__(self, ruleTag: _Optional[str] = ...) -> None: ...

class RemoveRuleResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListRuleRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListRuleItem(_message.Message):
    __slots__ = ("tag", "ruleTag")
    TAG_FIELD_NUMBER: _ClassVar[int]
    RULETAG_FIELD_NUMBER: _ClassVar[int]
    tag: str
    ruleTag: str
    def __init__(self, tag: _Optional[str] = ..., ruleTag: _Optional[str] = ...) -> None: ...

class ListRuleResponse(_message.Message):
    __slots__ = ("rules",)
    RULES_FIELD_NUMBER: _ClassVar[int]
    rules: _containers.RepeatedCompositeFieldContainer[ListRuleItem]
    def __init__(self, rules: _Optional[_Iterable[_Union[ListRuleItem, _Mapping]]] = ...) -> None: ...

class Config(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
