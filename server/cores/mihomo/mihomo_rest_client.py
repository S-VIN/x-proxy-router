"""Thin asynchronous REST wrapper using the standard library."""

import asyncio
import json
from http.client import HTTPConnection, HTTPException
from urllib.parse import quote

from .mihomo_process_manager import MihomoError


class MihomoRestClient:
    def __init__(self):
        self._port = None
        self._secret = None

    async def connect(self, port: int, secret: str) -> None:
        self._port, self._secret = port, secret
        try:
            async with asyncio.timeout(5):
                while True:
                    try:
                        await self.request("GET", "/version")
                        return
                    except MihomoError:
                        await asyncio.sleep(0.05)
        except TimeoutError:
            await self.close()
            raise MihomoError("Mihomo REST API did not become ready") from None

    async def close(self) -> None:
        self._port = self._secret = None

    async def request(self, method: str, path: str, body: dict | None = None):
        if self._port is None:
            raise RuntimeError("Connect the REST client first")
        return await asyncio.to_thread(self._request, self._port, self._secret, method, path, body)

    @staticmethod
    def _request(port, secret, method, path, body):
        # HTTPConnection bypasses environment HTTP proxies and does not follow redirects.
        connection = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(
                method,
                path,
                body=json.dumps(body) if body is not None else None,
                headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            )
            response = connection.getresponse()
            data = response.read()
            if not 200 <= response.status < 300:
                # API diagnostics may contain subscription passwords.
                raise MihomoError(f"Mihomo REST request failed (HTTP {response.status})")
            return json.loads(data) if data else None
        except (OSError, ValueError, HTTPException):
            raise MihomoError("Mihomo REST request failed") from None
        finally:
            connection.close()

    async def replace_config(self, config: dict) -> None:
        await self.request("PUT", "/configs?force=false", {"payload": json.dumps(config)})

    async def get_proxies(self) -> dict:
        return await self.request("GET", "/proxies")

    async def get_rules(self) -> dict:
        return await self.request("GET", "/rules")

    async def select_proxy(self, group: str, name: str) -> None:
        await self.request("PUT", f"/proxies/{quote(group, safe='')}", {"name": name})
