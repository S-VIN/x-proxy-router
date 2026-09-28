"""Shared services available to application handlers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..tasks import TaskRegistry

if TYPE_CHECKING:
    from ..cores.core_client import CoreClient
    from ..main import Scheduler, WebSocketServer
    from ..model_sync import ModelSync
    from ..settings_store import SettingsStore


@dataclass(frozen=True)
class ApplicationContext:
    settings: SettingsStore
    core_client: CoreClient
    scheduler: Scheduler
    websocket: WebSocketServer
    sync: ModelSync
    # Long tasks by name: refresh_subscriptions, test_outbound_servers (server/tasks.py).
    tasks: TaskRegistry = field(default_factory=TaskRegistry)
    # The core has one test endpoint, so servers are checked through it one at a time.
    outbound_test_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Serializes changes of the core's servers and its main route.
    core_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
