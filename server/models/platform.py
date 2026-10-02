"""Supported platforms; values match the resource directory names."""

from enum import StrEnum


class OperatingSystem(StrEnum):
    LINUX = "linux"
    WINDOWS = "win32"
    MACOS = "darwin"


class Architecture(StrEnum):
    X64 = "x64"
    ARM64 = "arm64"
