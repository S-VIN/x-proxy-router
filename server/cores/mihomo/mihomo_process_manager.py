"""Mihomo lifecycle; await operations sequentially and stop on application shutdown."""

import asyncio
import json
import logging
import secrets
import socket
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from ...models import CoreState, CoreStatus, OperatingSystem
from ...utils import detect_platform
from ..core_process_manager import CoreProcessManagerInterface

log = logging.getLogger(__name__)
RESOURCES = Path(__file__).resolve().parents[3] / "resources" / "mihomo"


class MihomoError(RuntimeError):
    """Mihomo could not complete a process or API operation."""


class MihomoProcessManager(CoreProcessManagerInterface):
    def __init__(self):
        self.api_port: int | None = None
        self.api_secret: str | None = None
        self._process = None
        self._task = None
        self._directory = None
        self._state = CoreState.STOPPED
        self._exit_code = None
        self._last_error = None

    @property
    def binary_path(self) -> Path:
        system, arch = detect_platform()
        return (
            RESOURCES
            / system.value
            / arch.value
            / ("mihomo.exe" if system is OperatingSystem.WINDOWS else "mihomo")
        )

    def status(self) -> CoreStatus:
        pid = self._process.pid if self._process and self._process.returncode is None else None
        return CoreStatus(self._state, pid, self._exit_code, self._last_error)

    def _generate_config(self) -> dict:
        return {
            "external-controller": f"127.0.0.1:{self.api_port}",
            "secret": self.api_secret,
            "log-level": "info",
            "mode": "rule",
            "allow-lan": False,
            "bind-address": "127.0.0.1",
            "find-process-mode": "off",
            "profile": {"store-selected": False, "store-fake-ip": False},
            "dns": {"enable": False},
            "listeners": [],
            "proxies": [],
            "proxy-groups": [
                {"name": role, "type": "select", "proxies": ["REJECT"]} for role in ("main", "test")
            ],
            "rules": ["IN-NAME,main,main", "IN-NAME,test,test", "MATCH,REJECT"],
        }

    async def start(self) -> None:
        if self._state != CoreState.STOPPED:
            raise MihomoError("Stop Mihomo before starting it again")
        self._state = CoreState.STARTING
        self._last_error = self._exit_code = None
        self._directory = TemporaryDirectory(prefix="mihomo-")
        try:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                self.api_port = listener.getsockname()[1]
            self.api_secret = secrets.token_urlsafe(32)
            path = Path(self._directory.name) / "config.json"
            path.write_text(json.dumps(self._generate_config()), encoding="utf-8")
            self._process = await asyncio.create_subprocess_exec(
                str(self.binary_path),
                "-d",
                self._directory.name,
                "-f",
                str(path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **(
                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                    if sys.platform == "win32"
                    else {}
                ),
            )
        except Exception as error:
            self._state = CoreState.FAILED
            self._last_error = "Cannot launch Mihomo"
            self._cleanup()
            raise MihomoError(self._last_error) from error
        self._state = CoreState.RUNNING
        self._task = asyncio.create_task(self._watch(), name="mihomo-monitor")

    async def _watch(self):
        process = self._process
        while chunk := await process.stdout.read(4096):
            log.info("Mihomo: %s", chunk.decode(errors="replace").rstrip())
        self._exit_code = await process.wait()
        self._process = None
        self.api_port = None
        if self._state != CoreState.STOPPING:
            self._state = CoreState.FAILED
            self._last_error = f"Mihomo exited with code {self._exit_code}"
        else:
            self._state = CoreState.STOPPED

    def _cleanup(self):
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
        self.api_port = self.api_secret = None

    async def stop(self) -> None:
        self._state = CoreState.STOPPING
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass
        if self._task is not None:
            await self._task
            self._task = None
        self._cleanup()
        self._state = CoreState.STOPPED
