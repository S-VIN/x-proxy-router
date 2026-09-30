"""Core interfaces."""

from .core_client import CoreClient, InboundError
from .core_process_manager import CoreProcessManagerInterface

__all__ = ["CoreClient", "CoreProcessManagerInterface", "InboundError"]
