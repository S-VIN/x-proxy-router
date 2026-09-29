"""Server data models and enumerations."""

from .platform import Architecture, OperatingSystem
from .core_state import CoreState, CoreStatus
from .serialization import SECRET, JsonValue, serialize
from .outbound_test import OutboundTest, OutboundTestRule
from .server_settings import ServerSettings
from .subscription_link import SubscriptionLink
from .reg_filter import RegFilter
from .task_state import TaskState, TaskStatus
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

__all__ = [
    "Architecture",
    "OperatingSystem",
    "CoreState",
    "CoreStatus",
    "SECRET",
    "JsonValue",
    "serialize",
    "ServerSettings",
    "SubscriptionLink",
    "RegFilter",
    "OutboundTest",
    "OutboundTestRule",
    "TaskState",
    "TaskStatus",
    "FilterReason",
    "OutboundProtocol",
    "OutboundSecurity",
    "OutboundServer",
    "OutboundTransport",
    "VlessFlow",
    "ShadowsocksMethod",
    "UotVersion",
    "GrpcMode",
    "XhttpMode",
]
