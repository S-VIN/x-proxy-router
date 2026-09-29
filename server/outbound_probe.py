"""Network checks of one outbound server: TCP ping to the server itself, and HTTP
requests through the core's SOCKS5 test endpoint.
"""

import asyncio
import socket
from contextlib import suppress
from ssl import SSLContext

from aiohttp import ClientError, ClientSession, ClientTimeout
from aiohttp.client_proto import ResponseHandler
from aiohttp_socks import ProxyConnector, ProxyError

from .models.outbound_test import OutboundTest

PING_ATTEMPTS = 3
# Seconds for the whole ping, name resolution included; an attempt still going
# at the deadline is abandoned, and a server with no attempt done counts as unreachable.
PING_LIMIT = 0.5
# Seconds for the whole speed test: connecting, response headers and download.
# The test downloads at most 1 Mbit/s for 2 seconds worth of data.
SPEED_TEST_DURATION = 2.0
SPEED_TEST_BYTES = 250_000
SPEED_TEST_URL = f"https://speed.cloudflare.com/__down?bytes={SPEED_TEST_BYTES}"
# Seconds for one outbound test to connect through the proxy and receive response headers.
TEST_TIMEOUT = 1

# Any of these means the request through the proxy got no response.
_REQUEST_ERRORS = (ClientError, ProxyError, OSError, TimeoutError)


async def tcp_ping(address: str, port: int) -> int | None:
    """Best TCP connect time in milliseconds of up to PING_ATTEMPTS attempts.

    The name is resolved once beforehand; DNS time counts towards PING_LIMIT
    but is not included in the result. Attempts go one after another until
    PING_LIMIT seconds pass; the one cut off by the deadline does not count.
    None if the name does not resolve or no attempt connects in time.
    """
    loop = asyncio.get_running_loop()
    best = None
    try:
        async with asyncio.timeout(PING_LIMIT):
            addresses = await loop.getaddrinfo(address.strip("[]"), port, type=socket.SOCK_STREAM)
            host = str(addresses[0][4][0])  # IP address of the first result
            for _ in range(PING_ATTEMPTS):
                started = loop.time()
                try:
                    _, writer = await asyncio.open_connection(host, port)
                except OSError:
                    continue
                elapsed = loop.time() - started
                # The connection may complete just before the deadline and be seen after it.
                if elapsed <= PING_LIMIT:
                    best = elapsed if best is None else min(best, elapsed)
                writer.close()
                with suppress(OSError):
                    await writer.wait_closed()
    except (OSError, TimeoutError):
        pass  # No name, or the deadline passed: keep the attempts done so far.
    return round(best * 1000) if best is not None else None


class _ProxyConnector(ProxyConnector):
    """ProxyConnector that runs the TLS handshake itself.

    ProxyConnector leaves TLS to python-socks, which on a cancelled handshake
    waits for the socket to close; on Python 3.12 that wait never ends. The
    core confirms a connection before the server behind it answers, so a slow
    server stalls the handshake, and the request cut off by its timeout would
    hang. Here a failed or cancelled handshake drops the connection at once.
    """

    async def _connect_via_proxy(
        self,
        host: str,
        port: int,
        ssl: SSLContext | None = None,
        timeout: float | None = None,
    ) -> tuple[asyncio.Transport, ResponseHandler]:
        transport, protocol = await super()._connect_via_proxy(host, port, timeout=timeout)
        if ssl is None:
            return transport, protocol
        try:
            tls_transport = await self._loop.start_tls(
                transport, protocol, ssl, server_hostname=host
            )
        except BaseException:
            transport.abort()
            raise
        if tls_transport is None:  # Not with asyncio's own event loops.
            transport.abort()
            raise ConnectionError("TLS was not started")
        protocol.connection_made(tls_transport)
        return tls_transport, protocol


def proxy_session(port: int) -> ClientSession:
    """HTTP client through the SOCKS5 test endpoint on 127.0.0.1.

    Host names are resolved by the proxy. Every request opens its own connection,
    so no connection outlives a switch of the test endpoint to another server.
    Environment proxy settings are ignored; timeouts are set per request.
    """
    connector = _ProxyConnector.from_url(f"socks5://127.0.0.1:{port}", rdns=True, force_close=True)
    return ClientSession(
        connector=connector, auto_decompress=False, timeout=ClientTimeout(total=None)
    )


async def download_speed(session: ClientSession) -> int:
    """Download speed in bytes per second; 0 if the download fails.

    The whole test, connecting included, takes at most SPEED_TEST_DURATION
    seconds. Counting starts when response headers arrive and stops after
    SPEED_TEST_BYTES or at the deadline, whichever comes first; the connection
    is then closed, so no more data is downloaded.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SPEED_TEST_DURATION
    try:
        async with asyncio.timeout_at(deadline):
            response = await session.get(
                SPEED_TEST_URL, allow_redirects=False, headers={"Accept-Encoding": "identity"}
            )
    except _REQUEST_ERRORS:
        return 0
    started = loop.time()
    received = 0
    try:
        if response.status != 200:
            return 0
        async with asyncio.timeout_at(deadline):
            async for chunk in response.content.iter_any():
                received += len(chunk)
                if received >= SPEED_TEST_BYTES:
                    break
    except _REQUEST_ERRORS:
        pass  # The deadline passed or the connection broke: count what arrived.
    finally:
        response.close()
    return round(received / max(loop.time() - started, 0.001))


async def run_test(session: ClientSession, test: OutboundTest) -> bool:
    """Whether the response status matches the test's rule; no response fails.

    Redirects are not followed: a 3xx status is the answer. Only the status is
    read; the connection is closed before the body is downloaded. No response
    within TEST_TIMEOUT seconds fails the test.
    """
    try:
        async with asyncio.timeout(TEST_TIMEOUT):
            response = await session.get(test.url, allow_redirects=False)
    except _REQUEST_ERRORS:
        return False
    response.close()
    return test.rule.accepts(response.status)
