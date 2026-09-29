"""Generate bindings using temporary dependencies, without pip or a venv setup.

Usage: python scripts/generate_grpc.py [/path/to/Xray-core]
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

VERSION = "26.3.27"

SERVICES = ["app/proxyman/command/command.proto", "app/router/command/command.proto"]
ROOTS = SERVICES + [
    "app/proxyman/config.proto",
    "app/router/config.proto",
    "proxy/socks/config.proto",
    "proxy/freedom/config.proto",
    "proxy/blackhole/config.proto",
    "proxy/vless/account.proto",
    "proxy/vless/outbound/config.proto",
    "proxy/shadowsocks/config.proto",
    "proxy/shadowsocks_2022/config.proto",
    "proxy/hysteria/config.proto",
    "transport/internet/hysteria/config.proto",
    *[
        f"transport/internet/{name}/config.proto"
        for name in ("tcp", "tls", "reality", "websocket", "grpc", "splithttp", "httpupgrade")
    ],
]


def download(url: str, target: Path):
    with urlopen(url, timeout=60) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)


def generate(source: Path, temporary: Path, environment: dict):
    destination = (
        Path(__file__).resolve().parents[1] / "server" / "cores" / "xray" / "grpc_generated"
    )
    files = set()

    def collect(name):
        if name in files:
            return
        files.add(name)
        for dependency in re.findall(
            r'^import "([^"]+)";', (source / name).read_text(), re.MULTILINE
        ):
            collect(dependency)

    for name in ROOTS:
        collect(name)
    with TemporaryDirectory(dir=temporary) as output:
        compiler = [sys.executable, "-m", "grpc_tools.protoc", f"-I{source}"]
        subprocess.run(
            compiler + [f"--python_out={output}", f"--pyi_out={output}", *sorted(files)],
            env=environment,
            check=True,
        )
        subprocess.run(
            compiler + [f"--grpc_python_out={output}", *SERVICES], env=environment, check=True
        )
        for path in Path(output).rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            text = re.sub(
                r"^from (app|common|core|proxy|transport)([.\w]*) import ",
                r"from server.cores.xray.grpc_generated.\1\2 import ",
                text,
                flags=re.MULTILINE,
            )
            text = re.sub(
                r"(BuildTopDescriptorsAndMessages\(DESCRIPTOR, ')([^']+)",
                r"\1server.cores.xray.grpc_generated.\2",
                text,
            )
            target = destination / path.relative_to(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            directory = target.parent
            while directory != destination.parent:
                (directory / "__init__.py").touch()
                directory = directory.parent
    shutil.copyfile(source / "LICENSE", destination / "LICENSE")
    print(f"Generated {len(files)} protobuf modules and {len(SERVICES)} services")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source", nargs="?", type=Path, help="Local Xray-core source; downloaded if omitted"
    )
    args = parser.parse_args()
    with TemporaryDirectory(prefix="xray-grpc-build-") as directory:
        temporary = Path(directory)
        # pip runs from a zip application and installs only into this temporary directory.
        print("Downloading build tools into a temporary directory...", flush=True)
        pip = temporary / "pip.pyz"
        download("https://bootstrap.pypa.io/pip/pip.pyz", pip)
        dependencies = temporary / "dependencies"
        subprocess.run(
            [
                sys.executable,
                str(pip),
                "--isolated",
                "--disable-pip-version-check",
                "install",
                "--target",
                str(dependencies),
                "--only-binary=:all:",
                "--no-cache-dir",
                "grpcio==1.78.0",
                "grpcio-tools==1.78.0",
                "protobuf==6.33.5",
            ],
            check=True,
        )
        environment = dict(os.environ, PYTHONPATH=str(dependencies), PYTHONNOUSERSITE="1")
        source = args.source
        if source is None:
            print(f"Downloading Xray-core v{VERSION} schemas...", flush=True)
            archive = temporary / "xray.zip"
            download(
                f"https://codeload.github.com/XTLS/Xray-core/zip/refs/tags/v{VERSION}", archive
            )
            source = temporary / "source"
            prefix = f"Xray-core-{VERSION}/"
            with ZipFile(archive) as zipped:
                for name in zipped.namelist():
                    if not name.startswith(prefix):
                        continue
                    relative = Path(name[len(prefix) :])
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError(f"Invalid archive path: {name}")
                    if relative.suffix == ".proto" or str(relative) == "LICENSE":
                        target = source / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(zipped.read(name))
        generate(source.resolve(), temporary, environment)


if __name__ == "__main__":
    main()
