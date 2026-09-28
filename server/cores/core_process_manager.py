"""Shared process lifecycle contract."""

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import CoreStatus


class CoreProcessManagerInterface(ABC):
    api_port: int | None

    @property
    @abstractmethod
    def binary_path(self) -> Path: ...

    @abstractmethod
    def status(self) -> CoreStatus: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...
