import os
import unittest
from unittest.mock import patch

from server.models import Architecture, OperatingSystem
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

    def test_macos_architectures(self):
        for machine, arch in (("arm64", Architecture.ARM64), ("x86_64", Architecture.X64)):
            with (
                patch("server.utils.platform.platform.machine", return_value=machine),
                patch("server.utils.platform.sys.platform", "darwin"),
                patch("server.utils.platform.struct.calcsize", return_value=8),
            ):
                self.assertEqual(detect_platform(), (OperatingSystem.MACOS, arch))

    def test_unsupported_32bit(self):
        with (
            patch("server.utils.platform.struct.calcsize", return_value=4),
            self.assertRaises(UnsupportedPlatformError),
        ):
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
