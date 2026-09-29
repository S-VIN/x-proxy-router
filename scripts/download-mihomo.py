#!/usr/bin/env python3
"""Download pinned official Mihomo binaries using only Python's standard library."""

import gzip
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

VERSION = "1.19.31"
ROOT = Path(__file__).resolve().parents[1] / "resources" / "mihomo"
RELEASE = f"https://github.com/MetaCubeX/mihomo/releases/download/v{VERSION}"
# Archive digests published by GitHub for this release.
ASSETS = {
    ("linux", "x64"): (
        "linux-amd64-compatible",
        "gz",
        "04cf9f09671704f839ddbee2e93069dc831a4123a75281e725d1d96ab9ac1afc",
    ),
    ("linux", "arm64"): (
        "linux-arm64",
        "gz",
        "9e0f11afbf38426b8bd88fdc594678f8161c57eccb4e1b77acb12b493904f1d4",
    ),
    ("win32", "x64"): (
        "windows-amd64-compatible",
        "zip",
        "93d14e9a13b49b2f2d256202d02cc8d14a7c4695edf084cae0f941986bc9c218",
    ),
    ("win32", "arm64"): (
        "windows-arm64",
        "zip",
        "68659624a38ae1dbc4e1b92f45d4dc75da0eaedd4d732b0a6f01a308da945792",
    ),
}


def download(url):
    with urlopen(Request(url, headers={"User-Agent": "x-proxy-router"}), timeout=120) as response:
        return response.read()


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": VERSION,
        "repository": "https://github.com/MetaCubeX/mihomo",
        "binaries": [],
    }
    for (system, arch), (platform, extension, digest) in ASSETS.items():
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
        directory = ROOT / system / arch
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / ("mihomo.exe" if system == "win32" else "mihomo")
        temporary = target.with_suffix(".download")
        temporary.write_bytes(binary)
        if system == "linux":
            temporary.chmod(0o755)
        temporary.replace(target)
        record = {
            "os": system,
            "architecture": arch,
            "path": str(target.relative_to(ROOT)),
            "url": url,
            "archive_sha256": digest,
            "sha256": hashlib.sha256(binary).hexdigest(),
        }
        (directory / "checksums.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        manifest["binaries"].append(record)
    (ROOT / "LICENSE").write_bytes(
        download(f"https://raw.githubusercontent.com/MetaCubeX/mihomo/v{VERSION}/LICENSE")
    )
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Installed Mihomo {VERSION} in {ROOT}")


if __name__ == "__main__":
    main()
