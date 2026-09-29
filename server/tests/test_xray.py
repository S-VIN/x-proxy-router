import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import XrayError, XrayProcessManager
from server.models import Architecture, CoreState, OperatingSystem
from server.utils import UnsupportedPlatformError, detect_platform


class PlatformTests(unittest.TestCase):
    def test_supported_aliases(self):
        for machine, arch in (("x86_64", Architecture.X64), ("aarch64", Architecture.ARM64)):
            with (
                patch("server.utils.platform.platform.machine", return_value=machine),
                patch("server.utils.platform.sys.platform", "linux"),
                patch("server.utils.platform.struct.calcsize", return_value=8),
            ):
                system, detected_arch = detect_platform()
                self.assertIs(system, OperatingSystem.LINUX)
                self.assertIs(detected_arch, arch)

    def test_unsupported_32bit(self):
        with patch("server.utils.platform.struct.calcsize", return_value=4):
            with self.assertRaises(UnsupportedPlatformError):
                detect_platform()

    def test_windows_emulated_process_architecture(self):
        with (
            patch("server.utils.platform.sys.platform", "win32"),
            patch("server.utils.platform.platform.machine", return_value="ARM64"),
            patch.dict(os.environ, {"PROCESSOR_ARCHITECTURE": "AMD64"}),
            patch("server.utils.platform.struct.calcsize", return_value=8),
        ):
            system, arch = detect_platform()
            self.assertIs(system, OperatingSystem.WINDOWS)
            self.assertIs(arch, Architecture.X64)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = XrayProcessManager()
        self.temp = tempfile.TemporaryDirectory()

    async def asyncTearDown(self):
        await self.manager.stop()
        self.temp.cleanup()

    async def wait_for(self, condition):
        async with asyncio.timeout(5):
            while not condition():
                await asyncio.sleep(0.01)

    async def wait_api(self, manager):
        async with asyncio.timeout(5):
            while True:
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", manager.api_port)
                    writer.close()
                    await writer.wait_closed()
                    return
                except OSError:
                    await asyncio.sleep(0.01)

    async def test_start_stop_start(self):
        await self.manager.start()
        await asyncio.sleep(0.1)
        self.assertEqual(self.manager.status().state, CoreState.RUNNING)
        pid = self.manager.status().pid
        await self.manager.stop()
        self.assertEqual(self.manager.status().state, CoreState.STOPPED)
        self.assertIsNone(self.manager.status().pid)
        await self.manager.stop()
        await self.manager.start()
        self.assertNotEqual(self.manager.status().pid, pid)

    async def test_two_managers_get_distinct_ports(self):
        other = XrayProcessManager()
        try:
            await self.manager.start()
            await self.wait_api(self.manager)
            await other.start()
            await self.wait_api(other)
            self.assertIsInstance(self.manager.api_port, int)
            self.assertGreater(self.manager.api_port, 0)
            self.assertNotEqual(self.manager.api_port, other.api_port)
        finally:
            await other.stop()
        self.assertIsNone(other.api_port)

    async def test_generated_config_and_api(self):
        await self.manager.start()
        path = self.manager._config
        config = json.loads(path.read_text())
        self.assertEqual(config["api"]["listen"], f"127.0.0.1:{self.manager.api_port}")
        self.assertGreater(self.manager.api_port, 0)
        await self.wait_api(self.manager)
        check = await asyncio.create_subprocess_exec(
            str(self.manager.binary_path),
            "run",
            "-test",
            "-config",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await check.communicate()
        self.assertEqual(check.returncode, 0, output.decode())
        query = await asyncio.create_subprocess_exec(
            str(self.manager.binary_path),
            "api",
            "lso",
            f"--server=127.0.0.1:{self.manager.api_port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await query.communicate()
        self.assertEqual(query.returncode, 0, output.decode())
        self.assertIn("blocked", output.decode())
        await self.manager.stop()
        self.assertFalse(path.exists())

    async def test_missing_binary(self):
        with patch(
            "server.cores.xray.xray_process_manager.RESOURCES", Path(self.temp.name) / "missing"
        ):
            with self.assertRaises(XrayError):
                await self.manager.start()
        self.assertEqual(self.manager.status().state, CoreState.FAILED)
        self.assertIsNone(self.manager._config_dir)
        self.assertIsNone(self.manager.api_port)

    async def test_crash_stays_failed(self):
        await self.manager.start()
        self.manager._process.kill()
        await self.wait_for(lambda: self.manager.status().state == CoreState.FAILED)
        await asyncio.sleep(0.1)
        self.assertEqual(self.manager.status().state, CoreState.FAILED)
        self.assertIsNone(self.manager.status().pid)
        self.assertIsNone(self.manager.api_port)
        self.assertNotEqual(self.manager.status().exit_code, 0)


if __name__ == "__main__":
    unittest.main()
