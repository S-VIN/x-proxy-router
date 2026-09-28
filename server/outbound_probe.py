"""Network checks of one outbound server: TCP ping to the server itself, and HTTP
requests through the core's SOCKS5 test endpoint.
"""

import asyncio
import socket
from contextlib import suppress

from aiohttp import ClientError, ClientSession, ClientTimeout
from aiohttp_socks import ProxyConnector, ProxyError

from .models.outbound_test import OutboundTest

PING_ATTEMPTS = 3
# Seconds; one attempt that takes longer is abandoned, and a server with no
# faster attempt counts as unreachable.
PING_LIMIT = 0.5
DNS_TIMEOUT = 5.0
# The speed test downloads at most 1 Mbit/s for 2 seconds worth of data.
SPEED_TEST_DURATION = 2.0
SPEED_TEST_BYTES = 250_000
SPEED_TEST_URL = f"https://speed.cloudflare.com/__down?bytes={SPEED_TEST_BYTES}"
# Seconds to connect through the proxy and receive response headers.
REQUEST_TIMEOUT = 5.0

# Any of these means the request through the proxy got no response.
_REQUEST_ERRORS = (ClientError, ProxyError, OSError, TimeoutError)


async def tcp_ping(address: str, port: int) -> int | None:
    """Best TCP connect time in milliseconds of PING_ATTEMPTS attempts.

    None if the name does not resolve or no attempt connects within PING_LIMIT.
    The name is resolved once beforehand, so DNS time is not included.
    """
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(DNS_TIMEOUT):
            addresses = await loop.getaddrinfo(address.strip("[]"), port, type=socket.SOCK_STREAM)
    except (OSError, TimeoutError):
        return None
    host = str(addresses[0][4][0])  # IP address of the first result
    best = None
    for _ in range(PING_ATTEMPTS):
        started = loop.time()
        try:
            async with asyncio.timeout(PING_LIMIT):
                _, writer = await asyncio.open_connection(host, port)
        except (OSError, TimeoutError):
            continue
        elapsed = loop.time() - started
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()
        # The connection may complete just before the deadline and be seen after it.
        if elapsed <= PING_LIMIT:
            best = elapsed if best is None else min(best, elapsed)
    return round(best * 1000) if best is not None else None


def proxy_session(port: int) -> ClientSession:
    """HTTP client through the SOCKS5 test endpoint on 127.0.0.1.

    Host names are resolved by the proxy. Every request opens its own connection,
    so no connection outlives a switch of the test endpoint to another server.
    Environment proxy settings are ignored; timeouts are set per request.
    """
    connector = ProxyConnector.from_url(f"socks5://127.0.0.1:{port}", rdns=True, force_close=True)
    return ClientSession(
        connector=connector, auto_decompress=False, timeout=ClientTimeout(total=None)
    )


async def download_speed(session: ClientSession) -> int:
    """Download speed in bytes per second; 0 if the download fails.

    Counting starts when response headers arrive and stops after SPEED_TEST_BYTES
    or SPEED_TEST_DURATION seconds, whichever comes first; the connection is then
    closed, so no more data is downloaded.
    """
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
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
        async with asyncio.timeout(SPEED_TEST_DURATION):
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
    read; the connection is closed before the body is downloaded.
    """
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            response = await session.get(test.url, allow_redirects=False)
    except _REQUEST_ERRORS:
        return False
    response.close()
    return test.rule.accepts(response.status)
