import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aiohttp import ClientSession
from yarl import URL

from server.main import WebSocketServer


class StaticFilesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.root = directory / "dist"
        (self.root / "assets").mkdir(parents=True)
        (self.root / "index.html").write_text("<!doctype html><title>app</title>")
        (self.root / "assets" / "index-abc123.js").write_text("export {};")
        (self.root / "favicon.svg").write_text("<svg></svg>")
        (directory / "secret.txt").write_text("secret")
        self.server = WebSocketServer()
        await self.server.start("127.0.0.1", 0, static_dir=self.root)
        self.addAsyncCleanup(self.server.close)
        self.session = await self.enterAsyncContext(ClientSession())

    def url(self, path: str) -> URL:
        return URL(f"http://127.0.0.1:{self.server.port}{path}", encoded=True)

    async def test_root_serves_index_without_caching(self):
        async with self.session.get(self.url("/")) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "text/html")
            self.assertEqual(response.headers["Cache-Control"], "no-cache")
            self.assertIn("<title>app</title>", await response.text())

    async def test_hashed_assets_are_cached_forever(self):
        async with self.session.get(self.url("/assets/index-abc123.js")) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "text/javascript")
            self.assertIn("immutable", response.headers["Cache-Control"])

    async def test_other_files_are_served(self):
        async with self.session.get(self.url("/favicon.svg")) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "image/svg+xml")

    async def test_missing_files_directories_and_escapes_are_not_found(self):
        for path in (
            "/missing.js",
            "/assets",
            "/assets/",
            "/..%2fsecret.txt",
            "/%2e%2e/secret.txt",
        ):
            async with self.session.get(self.url(path)) as response:
                self.assertEqual(response.status, 404, path)

    async def test_websocket_still_answers(self):
        async with self.session.ws_connect(self.url("/ws")) as ws:
            await ws.close()


class MissingBuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_build_is_logged_and_not_found(self):
        directory = self.enterContext(TemporaryDirectory())
        server = WebSocketServer()
        with self.assertLogs("server.static_files", level="WARNING"):
            await server.start("127.0.0.1", 0, static_dir=Path(directory) / "dist")
        self.addAsyncCleanup(server.close)
        async with (
            ClientSession() as session,
            session.get(f"http://127.0.0.1:{server.port}/") as response,
        ):
            self.assertEqual(response.status, 404)
