"""Core lifecycle data shared by server components."""

from dataclasses import dataclass
from enum import StrEnum


class CoreState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True)
class CoreStatus:
    state: CoreState
    pid: int | None
    exit_code: int | None
    last_error: str | None
