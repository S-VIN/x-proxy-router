import base64
import gzip
import json
import os
import threading
import unittest
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from server.models import OutboundProtocol, SubscriptionLink
from server.subscription_loader import SubscriptionError, load_subscription

URI = (
    "vless://00000000-0000-0000-0000-000000000001@example.com:443"
    "?type=ws&security=tls&path=%2Fws#Test"
)
LINKS_FILE = Path(__file__).resolve().parents[2] / "subscription_links.txt"


class _Handler(BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, tuple[dict[str, str], bytes]]] = {}
    user_agent: ClassVar[str | None] = None

    def do_GET(self):
        type(self).user_agent = self.headers["User-Agent"]
        headers, body = self.routes[self.path]
        self.send_response(200)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class LoaderTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        encoded = base64.b64encode(URI.encode())
        _Handler.routes = {
            "/plain": ({}, URI.encode()),
            "/base64": ({}, encoded),
            "/json": (
                {},
                json.dumps(
                    {
                        "outbounds": [
                            {
                                "protocol": "vless",
                                "tag": "Test",
                                "settings": {
                                    "vnext": [
                                        {
                                            "address": "example.com",
                                            "port": 443,
                                            "users": [
                                                {"id": "00000000-0000-0000-0000-000000000001"}
                                            ],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ).encode(),
            ),
            # Like your-durev.com: gzip body regardless of Accept-Encoding.
            "/gzip": ({"Content-Encoding": "gzip"}, gzip.compress(encoded)),
            "/gzip-unlabelled": ({}, gzip.compress(encoded)),
            "/deflate": ({"Content-Encoding": "deflate"}, zlib.compress(encoded)),
            "/br": ({"Content-Encoding": "br"}, b"\x00"),
            "/html": ({}, b"<html>error</html>"),
            "/big": ({}, b"x" * 64),
            "/bomb": ({"Content-Encoding": "gzip"}, gzip.compress(b"x" * 10_000)),
        }
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()

    async def test_plain_and_compressed_bodies(self):
        for path in ("/plain", "/base64", "/json", "/gzip", "/gzip-unlabelled", "/deflate"):
            with self.subTest(path=path):
                link = SubscriptionLink(url=self.base + path)
                servers = await load_subscription(link)
                self.assertEqual(len(servers), 1)
                self.assertEqual(servers[0].name, "Test")
                self.assertEqual(servers[0].subscription_id, link.id)
        self.assertEqual(_Handler.user_agent, "v2rayN/7.0")

    async def test_proxy_settings_are_ignored(self):
        # Nothing listens on port 1: a request through the proxy would fail.
        proxy = "http://127.0.0.1:1"
        variables = ("http_proxy", "https_proxy", "all_proxy")
        environment = {name: proxy for name in variables} | {
            name.upper(): proxy for name in variables
        }
        with patch.dict(os.environ, environment):
            for name in ("no_proxy", "NO_PROXY"):
                os.environ.pop(name, None)
            servers = await load_subscription(self.base + "/plain")
        self.assertEqual(len(servers), 1)

    async def test_direct_vless_link_does_not_download(self):
        with patch("server.subscription_loader._download") as download:
            servers = await load_subscription(URI)
        download.assert_not_called()
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0].name, "Test")
        self.assertEqual(servers[0].address, "example.com")
        self.assertEqual(servers[0].protocol, OutboundProtocol.VLESS)

    async def test_invalid_direct_link_hides_credentials(self):
        with self.assertRaises(SubscriptionError) as error:
            await load_subscription("vless://secret@example.com:443")
        self.assertNotIn("secret", str(error.exception))
        self.assertNotIn("example.com", str(error.exception))

    async def test_string_url_gets_new_subscription_id(self):
        first, second = [await load_subscription(self.base + "/plain") for _ in range(2)]
        self.assertNotEqual(first[0].subscription_id, second[0].subscription_id)

    @patch("server.subscription_loader._MAX_SIZE", 32)
    async def test_errors_hide_url(self):
        for path in ("/br", "/html", "/big", "/bomb", "/missing"):
            with self.subTest(path=path), self.assertRaises(SubscriptionError) as error:
                await load_subscription(self.base + path)
            self.assertNotIn(path, str(error.exception))
        with self.assertRaises(ValueError):
            await load_subscription("ftp://example.com/sub")


@unittest.skipUnless(
    os.environ.get("LIVE_SUBSCRIPTIONS") and LINKS_FILE.exists(),
    "set LIVE_SUBSCRIPTIONS=1 and create subscription_links.txt",
)
class LiveSubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_subscriptions(self):
        urls = [line.strip() for line in LINKS_FILE.read_text().splitlines() if line.strip()]
        for number, url in enumerate(urls, 1):
            with self.subTest(link=number):
                servers = await load_subscription(url)
                self.assertTrue(servers)
                self.assertTrue(all(s.protocol in OutboundProtocol for s in servers))
