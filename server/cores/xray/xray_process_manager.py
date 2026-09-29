"""Small asynchronous Xray manager; lifecycle calls must be made sequentially."""

import asyncio
import json
import logging
import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory

from ...models import CoreState, CoreStatus, OperatingSystem
from ...utils import detect_platform, start_child_process
from ..core_process_manager import CoreProcessManagerInterface

log = logging.getLogger(__name__)
RESOURCES = Path(__file__).resolve().parents[3] / "resources" / "xray"


class XrayError(RuntimeError):
    """Xray could not be launched."""


class XrayProcessManager(CoreProcessManagerInterface):
    """Use the shared `xray` instance from one event loop.

    No concurrency locks, cancellation cleanup, or parent-death protection.
    The application must await stop() during normal shutdown.
    """

    def __init__(self):
        self.api_port: int | None = None
        self._process = None
        self._task = None
        self._config = None
        self._config_dir = None
        self._state = CoreState.STOPPED
        self._exit_code = None
        self._last_error = None
        self._running = False

    @property
    def binary_path(self) -> Path:
        system, arch = detect_platform()
        executable = "xray.exe" if system is OperatingSystem.WINDOWS else "xray"
        return RESOURCES / system.value / arch.value / executable

    def status(self) -> CoreStatus:
        pid = self._process.pid if self._process and self._process.returncode is None else None
        return CoreStatus(self._state, pid, self._exit_code, self._last_error)

    def _generate_config(self) -> dict:
        """Build the bootstrap config using the previously selected API port."""
        return {
            "log": {"access": "none", "loglevel": "info"},
            "api": {
                "tag": "api",
                "listen": f"127.0.0.1:{self.api_port}",
                "services": ["HandlerService", "RoutingService"],
            },
            "routing": {"domainStrategy": "AsIs", "rules": []},
            "outbounds": [{"tag": "blocked", "protocol": "blackhole"}],
        }

    async def start(self) -> None:
        """Generate a minimal config and start Xray with a local gRPC endpoint."""
        if self._task is not None and not self._task.done():
            raise XrayError("Xray is already managed; call stop() before start()")
        self._remove_config()
        self._config_dir = TemporaryDirectory(prefix="x-proxy-router-")
        self._config = Path(self._config_dir.name) / "config.json"
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                self.api_port = listener.getsockname()[1]
            self._config.write_text(
                json.dumps(self._generate_config(), indent=2) + "\n", encoding="utf-8"
            )
            await self._launch()
        except Exception:
            self.api_port = None
            self._remove_config()
            raise
        self._running = True
        self._task = asyncio.create_task(self._watch(), name="xray-monitor")
        self._state = CoreState.RUNNING

    def _remove_config(self):
        if self._config_dir is not None:
            self._config_dir.cleanup()
            self._config_dir = None
            self._config = None

    async def _launch(self):
        self._state = CoreState.STARTING
        self._last_error = None
        self._exit_code = None
        try:
            binary = self.binary_path
            self._process = await start_child_process(
                str(binary),
                "run",
                "-config",
                str(self._config),
                env=dict(os.environ, XRAY_LOCATION_ASSET=str(binary.parent)),
            )
        except Exception as error:
            self._state = CoreState.FAILED
            self._last_error = str(error)
            raise XrayError(f"Cannot launch Xray: {error}") from error

    def _terminate(self):
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass

    async def _watch(self):
        process = self._process
        # start() creates the process with stdout=PIPE before it starts this task.
        assert process is not None and process.stdout is not None
        # Merge stdout/stderr and drain in this same task, including long lines.
        while chunk := await process.stdout.read(4096):
            log.info("Xray: %s", chunk.decode(errors="replace").rstrip())
        self._exit_code = await process.wait()
        self._process = None
        self.api_port = None
        if self._running:
            self._state = CoreState.FAILED
            self._last_error = f"Xray exited unexpectedly with code {self._exit_code}"
            log.warning(self._last_error)
        else:
            self._state = CoreState.STOPPED

    async def stop(self) -> None:
        """Terminate and wait, without timeout or cancellation handling."""
        self._running = False
        self._state = CoreState.STOPPING
        self._terminate()
        if self._task is not None:
            await self._task
        self._remove_config()
        self.api_port = None
        self._state = CoreState.STOPPED


# Import this object wherever the server needs to control Xray.
xray = XrayProcessManager()
