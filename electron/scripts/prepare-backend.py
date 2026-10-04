#!/usr/bin/env python3
"""Stage the server for the desktop application of one OS and architecture.

The result, build/backend/<os>-<arch>, is laid out like the repository, so the
server finds the web client and the core as it does there:

    python/                         a standalone CPython with the packages of uv.lock
    server/                         the server, without its tests
    web/dist/                       the built web client (npm run build in web/)
    resources/mihomo/<os>/<arch>/   the core of this platform only

electron-builder packs the folder as the resource "backend". Needs uv and access
to GitHub and PyPI; uses only Python's standard library.
"""

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from urllib.request import Request, urlopen

ELECTRON = Path(__file__).resolve().parents[1]
ROOT = ELECTRON.parent
CACHE = ELECTRON / "build" / "cache"

# https://github.com/astral-sh/python-build-standalone: CPython that runs from any
# folder. The digests are the ones GitHub publishes for the release.
PYTHON_VERSION = "3.14.8"
PYTHON_RELEASE = "20261003"
# Folder of the standard library on Linux and macOS.
PYTHON_LIBRARY = "lib/python" + ".".join(PYTHON_VERSION.split(".")[:2])
PYTHON_URL = "https://github.com/astral-sh/python-build-standalone/releases/download"
# (os, arch) as electron-builder names them: the build's triple and its archive digest.
PYTHONS = {
    ("linux", "x64"): (
        "x86_64-unknown-linux-gnu",
        "d9ec7a6935ade8b671a57ebaf111083d7314eab8dae5071d167054dadd2b97d6",
    ),
    ("linux", "arm64"): (
        "aarch64-unknown-linux-gnu",
        "ece2bf3d4b47c80c2403c5f32fa51a9458abaee93c10def8acafb5f45163e77d",
    ),
    ("win", "x64"): (
        "x86_64-pc-windows-msvc",
        "10e5705e44938ee78de35c62b30fdfe2945b53438343d04c0f53548cdd8e91b6",
    ),
    ("win", "arm64"): (
        "aarch64-pc-windows-msvc",
        "a54c6bed6a239d044ae219be9ddee772959d049fb9b03fe4e1fbbba7598ad2ba",
    ),
    ("mac", "x64"): (
        "x86_64-apple-darwin",
        "08310045a2611bad730d7c1a01e847a1ea729d9dcfe29110ca67cbdf3998bb54",
    ),
    ("mac", "arm64"): (
        "aarch64-apple-darwin",
        "ed14e9042f36c0aa18383f5d9729bcbf17847e842666a793b5a5a5d8505c0ca1",
    ),
}
# Folder of the core in resources/mihomo, named as Node.js names the platform.
MIHOMO_SYSTEMS = {"linux": "linux", "win": "win32", "mac": "darwin"}

# Parts of the standard library the server never imports, relative to it.
UNUSED_LIBRARY = [
    "test",
    "idlelib",
    "tkinter",
    "turtledemo",
    "turtle.py",
    "ensurepip",
    "lib2to3",
    "site-packages/pip",
    "site-packages/pip-*.dist-info",
]
# Files of the Python build that only serve building, embedding or Tk.
UNUSED_UNIX_PYTHON = [
    "include",
    "share",
    "lib/pkgconfig",
    # The executable is linked statically; the library is for embedding.
    "lib/libpython3*",
    "lib/libtcl*",
    "lib/tcl*",
    "lib/tk*",
    "lib/itcl*",
    "lib/thread*",
    f"{PYTHON_LIBRARY}/lib-dynload/_tkinter*",
    "bin/2to3*",
    "bin/idle3*",
    "bin/pip*",
    "bin/pydoc3*",
    "bin/python3*-config",
]
UNUSED_PYTHON = {
    "linux": UNUSED_UNIX_PYTHON,
    "mac": UNUSED_UNIX_PYTHON,
    "win": [
        "include",
        "libs",
        "tcl",
        "Scripts",
        "DLLs/_tkinter.pyd",
        "DLLs/tcl*.dll",
        "DLLs/tk*.dll",
        "DLLs/_test*.pyd",
        "DLLs/_ctypes_test.pyd",
    ],
}


def host_target() -> tuple[str, str]:
    systems = {"linux": "linux", "win32": "win", "darwin": "mac"}
    machines = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}
    return systems.get(sys.platform, sys.platform), machines.get(
        platform.machine().lower(), platform.machine()
    )


def run(*command: str | Path, cwd: Path | None = None) -> None:
    print("+", *command, flush=True)
    subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def download(url: str, digest: str) -> Path:
    """The file of the URL, from the cache when its digest is right."""
    target = CACHE / url.rsplit("/", 1)[1]
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        return target
    print(f"Downloading {url}", flush=True)
    with urlopen(Request(url, headers={"User-Agent": "x-proxy-router"}), timeout=300) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError(f"SHA256 mismatch: {url}")
    CACHE.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def remove(directory: Path, patterns: list[str]) -> None:
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()


def stage_python(stage: Path, system: str, arch: str) -> Path:
    """Unpack Python without what the server does not use; returns the standard library."""
    triple, digest = PYTHONS[system, arch]
    archive = download(
        f"{PYTHON_URL}/{PYTHON_RELEASE}/cpython-{PYTHON_VERSION}+{PYTHON_RELEASE}"
        f"-{triple}-install_only_stripped.tar.gz",
        digest,
    )
    with tarfile.open(archive) as tar:
        tar.extractall(stage, filter="data")  # Everything is inside python/.
    python = stage / "python"
    library = python / ("Lib" if system == "win" else PYTHON_LIBRARY)
    remove(python, UNUSED_PYTHON[system])
    remove(library, UNUSED_LIBRARY)
    for cache in python.rglob("__pycache__"):
        shutil.rmtree(cache)
    return library


def install_packages(library: Path, triple: str) -> None:
    """The packages of uv.lock, as wheels of the target platform; nothing is built."""
    requirements = CACHE / "requirements.txt"
    CACHE.mkdir(parents=True, exist_ok=True)
    run(
        "uv", "export", "--quiet", "--locked", "--no-dev", "--no-emit-project", "--no-header",
        "--format", "requirements.txt", "--output-file", requirements,
        cwd=ROOT,
    )  # fmt: skip
    run(
        "uv", "pip", "install", "--no-deps", "--require-hashes", "--only-binary", ":all:",
        "--python", sys.executable,
        "--python-platform", triple,
        "--python-version", PYTHON_VERSION,
        "--target", library / "site-packages",
        "--requirement", requirements,
    )  # fmt: skip


def stage_application(stage: Path, system: str, arch: str) -> None:
    shutil.copytree(
        ROOT / "server",
        stage / "server",
        ignore=shutil.ignore_patterns("tests", "__pycache__", "*.md", "requirements.txt"),
    )
    web = ROOT / "web" / "dist"
    if not (web / "index.html").is_file():
        raise SystemExit("The web client is not built: run npm ci && npm run build in web/")
    shutil.copytree(web, stage / "web" / "dist")

    mihomo = ROOT / "resources" / "mihomo"
    directory = Path(MIHOMO_SYSTEMS[system]) / arch
    binary = directory / ("mihomo.exe" if system == "win" else "mihomo")
    (stage / "resources" / "mihomo" / directory).mkdir(parents=True)
    shutil.copy2(mihomo / "LICENSE", stage / "resources" / "mihomo" / "LICENSE")
    shutil.copy2(mihomo / binary, stage / "resources" / "mihomo" / binary)
    if system != "win":
        (stage / "resources" / "mihomo" / binary).chmod(0o755)


def compile_and_check(stage: Path, system: str, library: Path) -> None:
    """Bytecode for a read-only installation, and a start of the server's imports."""
    python = stage / "python" / ("python.exe" if system == "win" else "bin/python3")
    # unchecked-hash: valid whatever the packaging does to the files' times.
    run(
        python, "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
        library, stage / "server",
    )  # fmt: skip
    run(python, "-E", "-s", "-B", "-c", "import server.main", cwd=stage)


def main() -> None:
    host = host_target()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--os", choices=["linux", "win", "mac"], default=host[0])
    parser.add_argument("--arch", choices=["x64", "arm64"], default=host[1])
    arguments = parser.parse_args()
    system, arch = arguments.os, arguments.arch

    stage = ELECTRON / "build" / "backend" / f"{system}-{arch}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    library = stage_python(stage, system, arch)
    install_packages(library, PYTHONS[system, arch][0])
    stage_application(stage, system, arch)
    if (system, arch) == host:
        compile_and_check(stage, system, library)
    else:
        # The Python of another platform cannot run here; the server then compiles
        # its modules at every start.
        print(f"Not compiled and not checked: {system}-{arch} is not this computer")
    size = sum(path.stat().st_size for path in stage.rglob("*") if path.is_file())
    print(f"Staged {stage.relative_to(ROOT)}: {size / 1024 / 1024:.0f} MB")


if __name__ == "__main__":
    main()
