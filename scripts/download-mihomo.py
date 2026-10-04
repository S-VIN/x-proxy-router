#!/usr/bin/env python3
"""Download pinned official Mihomo binaries using only Python's standard library."""

import gzip
import hashlib
import io
import json
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
# The variables of the builds (README.md): here the name, the version of Mihomo and the
# digests of its archives, the ones GitHub publishes for the release.
BUILD = json.loads((ROOT / "build.json").read_text(encoding="utf-8"))
VERSION = BUILD["mihomo"]["version"]
MIHOMO = ROOT / "resources" / "mihomo"
RELEASE = f"https://github.com/MetaCubeX/mihomo/releases/download/v{VERSION}"
# (system as Node.js names it, arch): the system of build.json, the asset and its archive.
ASSETS = {
    ("linux", "x64"): ("linux", "linux-amd64-compatible", "gz"),
    ("linux", "arm64"): ("linux", "linux-arm64", "gz"),
    ("win32", "x64"): ("windows", "windows-amd64-compatible", "zip"),
    ("win32", "arm64"): ("windows", "windows-arm64", "zip"),
    ("darwin", "x64"): ("macos", "darwin-amd64-compatible", "gz"),
    ("darwin", "arm64"): ("macos", "darwin-arm64", "gz"),
}


def download(url):
    with urlopen(Request(url, headers={"User-Agent": BUILD["name"]}), timeout=120) as response:
        return response.read()


def main():
    MIHOMO.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": VERSION,
        "repository": "https://github.com/MetaCubeX/mihomo",
        "binaries": [],
    }
    for (system, arch), (name, platform, extension) in ASSETS.items():
        digest = BUILD["mihomo"]["sha256"][f"{name}-{arch}"]
        asset = f"mihomo-{platform}-v{VERSION}.{extension}"
        url = f"{RELEASE}/{asset}"
        print(f"Downloading {asset}", flush=True)
        archive = download(url)
        if hashlib.sha256(archive).hexdigest() != digest:
            raise RuntimeError(f"SHA256 mismatch: {asset}")
        if extension == "gz":
            binary = gzip.decompress(archive)
        else:
            with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                executables = [name for name in zipped.namelist() if name.endswith(".exe")]
                if len(executables) != 1:
                    raise RuntimeError(f"Unexpected archive contents: {asset}")
                binary = zipped.read(executables[0])
        directory = MIHOMO / system / arch
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / ("mihomo.exe" if system == "win32" else "mihomo")
        temporary = target.with_suffix(".download")
        temporary.write_bytes(binary)
        if system != "win32":
            temporary.chmod(0o755)
        temporary.replace(target)
        record = {
            "os": system,
            "architecture": arch,
            "path": str(target.relative_to(MIHOMO)),
            "url": url,
            "archive_sha256": digest,
            "sha256": hashlib.sha256(binary).hexdigest(),
        }
        (directory / "checksums.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        manifest["binaries"].append(record)
    (MIHOMO / "LICENSE").write_bytes(
        download(f"https://raw.githubusercontent.com/MetaCubeX/mihomo/v{VERSION}/LICENSE")
    )
    (MIHOMO / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Installed Mihomo {VERSION} in {MIHOMO}")


if __name__ == "__main__":
    main()
