#!/usr/bin/env python3
"""Download pinned official Mihomo binaries using only Python's standard library."""

import gzip
import hashlib
import io
import json
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

VERSION = "1.19.32"
ROOT = Path(__file__).resolve().parents[1] / "resources" / "mihomo"
RELEASE = f"https://github.com/MetaCubeX/mihomo/releases/download/v{VERSION}"
# Archive digests published by GitHub for this release.
ASSETS = {
    ("linux", "x64"): (
        "linux-amd64-compatible",
        "gz",
        "ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20",
    ),
    ("linux", "arm64"): (
        "linux-arm64",
        "gz",
        "9dd862e28b46ff7d775f169cceebc28deccaa0a9e804237d421cd2571e0caba0",
    ),
    ("win32", "x64"): (
        "windows-amd64-compatible",
        "zip",
        "974a4d7ad69aed27aa2e8f91d61113573c14dadb14562c63e58effabf59816f0",
    ),
    ("win32", "arm64"): (
        "windows-arm64",
        "zip",
        "7a4f6e58af9a120920935f2150cf642d945085fdb3e753314505b334234e1d1e",
    ),
    ("darwin", "x64"): (
        "darwin-amd64-compatible",
        "gz",
        "18b382df77bded2ad0fb3db27db5636cb15b20729d5ba995a357eeb9b46bf507",
    ),
    ("darwin", "arm64"): (
        "darwin-arm64",
        "gz",
        "3312a6780652c622890fd4357c6a853bbf865464fd047ac7b7f52dab8de18652",
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
        if system != "win32":
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
