"""Opt-in Docker smoke test: TLS login, protected assets/WS, and backend mutation.

Run after building the image:
  docker build -f docker/Dockerfile -t x-proxy:vless-test .
  uv run python scripts/test-docker-auth.py
Uses disposable containers, random loopback ports, and temporary credentials.
"""

import asyncio
import re
import secrets
import socket
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import aiohttp
from aiohttp.abc import AbstractResolver

ROOT = Path(__file__).resolve().parent.parent


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LocalResolver(AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        return [
            {
                "hostname": host,
                "host": "127.0.0.1",
                "port": port,
                "family": socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
        ]

    async def close(self):
        pass


async def main():
    ui, auth, https = port(), port(), port()
    base = f"https://panel.xpr.test:{https}"
    login = f"https://auth.xpr.test:{https}"
    password = secrets.token_urlsafe(24)
    entry = docker(
        "run",
        "--rm",
        "ghcr.io/tinyauthapp/tinyauth:v5",
        "user",
        "create",
        "--username",
        "smoketest",
        "--password",
        password,
    )
    # CLI prints explanatory text around the generated entry.
    match = re.search(r"smoketest:\$2[aby]\$\d+\$[./A-Za-z0-9]+", entry)
    assert match is not None, "Tinyauth did not produce a user entry"
    entry = match.group()
    containers = []
    with TemporaryDirectory(prefix="xpr-auth-test-") as directory:
        config = (ROOT / "docker/Caddyfile").read_text()
        config = re.sub(
            r"tls \{\s*issuer acme \{\s*disable_tlsalpn_challenge\s*\}\s*\}", "tls internal", config
        )
        config = config.replace(
            "https_port 8443",
            f"https_port {https}\n\tauto_https disable_redirects\n\tdefault_bind 127.0.0.1",
        )
        config = (
            config.replace("8443", str(https)).replace("20800", str(ui)).replace("20801", str(auth))
        )
        path = Path(directory) / "Caddyfile"
        path.write_text(config)

        def start(image, env, extra=()):
            args = ["run", "-d", "--rm", "--network", "host"]
            for key, value in env.items():
                args.extend(["-e", f"{key}={value}"])
            containers.append(docker(*args, *extra, image))

        try:
            start(
                "x-proxy:vless-test",
                {
                    "XPR_UI_HOST": "127.0.0.1",
                    "XPR_UI_PORT": str(ui),
                    "XPR_DATA_DIR": "/data",
                    "XPR_PUBLIC_ORIGIN": base,
                },
            )
            start(
                "ghcr.io/tinyauthapp/tinyauth:v5",
                {
                    "TINYAUTH_SERVER_ADDRESS": "127.0.0.1",
                    "TINYAUTH_SERVER_PORT": str(auth),
                    "TINYAUTH_APPURL": login,
                    "TINYAUTH_AUTH_USERS": entry,
                    "TINYAUTH_AUTH_SECURECOOKIE": "true",
                    "TINYAUTH_AUTH_TRUSTEDPROXIES": "127.0.0.1/32",
                },
            )
            start(
                "caddy:2-alpine",
                {"XPR_PANEL_DOMAIN": "panel.xpr.test", "XPR_AUTH_DOMAIN": "auth.xpr.test"},
                ["-v", f"{path}:/etc/caddy/Caddyfile:ro,Z"],
            )
            connector = aiohttp.TCPConnector(resolver=LocalResolver(), ssl=False)
            async with aiohttp.ClientSession(
                connector=connector,
                headers={
                    "Accept": "text/html",
                    "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
                },
            ) as session:
                for attempt in range(100):
                    try:
                        async with session.get(login, allow_redirects=False) as response:
                            if response.status == 200:
                                break
                    except aiohttp.ClientError:
                        pass
                    await asyncio.sleep(0.1)
                else:
                    raise RuntimeError("Auth stack did not start")
                for attempt in range(100):
                    try:
                        async with session.get(f"http://127.0.0.1:{ui}/") as response:
                            if response.status == 200:
                                break
                    except aiohttp.ClientError:
                        pass
                    await asyncio.sleep(0.1)
                else:
                    raise RuntimeError("Backend did not start")
                for route in ("/", "/ws", "/assets/anything.js"):
                    async with session.get(base + route, allow_redirects=False) as response:
                        assert response.status in (302, 303, 307), (route, response.status)
                        assert response.headers["Location"].startswith(login)
                async with session.post(
                    login + "/api/user/login", json={"username": "smoketest", "password": password}
                ) as response:
                    assert response.status == 200, response.status
                async with session.get(base) as response:
                    assert response.status == 200, (response.status, str(response.url))
                    assert "<html" in await response.text()
                async with session.ws_connect(base + "/ws", origin=base) as ws:
                    await ws.send_json(
                        {
                            "type": "change",
                            "model": "server_settings",
                            "request_id": "smoke",
                            "payload": {"id": 0, "outbound_mode": "server"},
                        }
                    )
                    async with asyncio.timeout(5):
                        async for message in ws:
                            data = message.json()
                            if data["type"] == "response":
                                assert data["ok"], data
                                break
                async with session.post(login + "/api/user/logout") as response:
                    assert response.status == 200, (response.status, str(response.url))
                async with session.get(base + "/ws", allow_redirects=False) as response:
                    assert response.status in (302, 303, 307)
            print(
                "PASS: anonymous assets/WS blocked; login, panel, WebSocket mutation and logout verified."
            )
        finally:
            for container in reversed(containers):
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "rm", "-f", "-v", container],
                    capture_output=True,
                    check=False,
                )


if __name__ == "__main__":
    asyncio.run(main())
