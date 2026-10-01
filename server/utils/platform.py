"""Platform names used by resources/mihomo (architecture of this Python runtime)."""

import platform
import struct
import sys

from ..models import Architecture, OperatingSystem


class UnsupportedPlatformError(RuntimeError):
    pass


def detect_platform() -> tuple[OperatingSystem, Architecture]:
    """Return OS and architecture enums; reject unsupported 32-bit runtimes."""
    machine = platform.machine().lower()
    try:
        system = OperatingSystem(sys.platform)
    except ValueError:
        raise UnsupportedPlatformError(f"Unsupported OS: {sys.platform}") from None
    if struct.calcsize("P") != 8:
        raise UnsupportedPlatformError(f"Unsupported platform: {sys.platform}/{machine}")
    # Windows platform.machine() can describe the native OS under emulation.
    # PROCESSOR_ARCHITECTURE describes the process environment instead.
    if system is OperatingSystem.WINDOWS:
        import os

        machine = os.environ.get("PROCESSOR_ARCHITECTURE", machine).lower()
    aliases = {
        "amd64": Architecture.X64,
        "x86_64": Architecture.X64,
        "arm64": Architecture.ARM64,
        "aarch64": Architecture.ARM64,
    }
    try:
        return system, aliases[machine]
    except KeyError:
        raise UnsupportedPlatformError(f"Unsupported architecture: {machine}") from None
