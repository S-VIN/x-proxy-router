"""State of one long task (server/tasks.py), sent to clients as the "task" model."""

from dataclasses import dataclass
from enum import StrEnum


class TaskStatus(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"


@dataclass(frozen=True, kw_only=True)
class TaskState:
    # The task name given to @long_task, e.g. "refresh_subscriptions".
    id: str
    status: TaskStatus
