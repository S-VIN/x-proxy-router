"""Server data models and enumerations."""

from .core_state import CoreState, CoreStatus
from .inbound_server import DEFAULT_PROXY_PORT, InboundFieldError, InboundServer, InboundType
from .outbound_server import (
    FilterReason,
    GrpcMode,
    OutboundProtocol,
    OutboundSecurity,
    OutboundServer,
    OutboundTransport,
    ShadowsocksMethod,
    UotVersion,
    VlessFlow,
    XhttpMode,
)
from .outbound_test import OutboundTest, OutboundTestRule
from .pattern import pattern_matches
from .platform import Architecture, OperatingSystem
from .reg_filter import RegFilter
from .routing_rule import RoutingAction, RoutingRule, RoutingRuleFieldError
from .serialization import SECRET, JsonValue, serialize
from .server_settings import ServerSettings
from .subscription_link import SubscriptionLink
from .task_state import TaskState, TaskStatus

__all__ = [
    "DEFAULT_PROXY_PORT",
    "SECRET",
    "Architecture",
    "CoreState",
    "CoreStatus",
    "FilterReason",
    "GrpcMode",
    "InboundFieldError",
    "InboundServer",
    "InboundType",
    "JsonValue",
    "OperatingSystem",
    "OutboundProtocol",
    "OutboundSecurity",
    "OutboundServer",
    "OutboundTest",
    "OutboundTestRule",
    "OutboundTransport",
    "RegFilter",
    "RoutingAction",
    "RoutingRule",
    "RoutingRuleFieldError",
    "ServerSettings",
    "ShadowsocksMethod",
    "SubscriptionLink",
    "TaskState",
    "TaskStatus",
    "UotVersion",
    "VlessFlow",
    "XhttpMode",
    "pattern_matches",
    "serialize",
]
