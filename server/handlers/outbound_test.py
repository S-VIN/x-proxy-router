"""Check one outbound server and store its health: ping, speed, tests and rating."""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace

from aiohttp import ClientSession

from ..models.application_context import ApplicationContext
from ..models.outbound_server import (
    FilterReason,
    OutboundProtocol,
    OutboundServer,
    OutboundTransport,
)
from ..models.outbound_test import OutboundTest
from ..outbound_probe import (
    PING_LIMIT,
    SPEED_TEST_BYTES,
    SPEED_TEST_DURATION,
    download_speed,
    proxy_session,
    run_test,
    tcp_ping,
)
from ..tasks import long_task

log = logging.getLogger(__name__)

# Rating weights; a part that is not measured does not count.
PING_WEIGHT = 30
SPEED_WEIGHT = 30
TESTS_WEIGHT = 40
# Bytes per second that earn full speed points: 1 Mbit/s, the most the test downloads.
FULL_SPEED = SPEED_TEST_BYTES / SPEED_TEST_DURATION


def uses_tcp(server: OutboundServer) -> bool:
    """Hysteria runs over QUIC (UDP), so a TCP connection says nothing about it."""
    return (
        server.protocol != OutboundProtocol.HYSTERIA
        and server.transport != OutboundTransport.HYSTERIA
    )


def server_rating(ping: int | None, speed: int, tests: dict[str, bool]) -> int:
    """Rating from 0 to 100 of a server that answered the ping.

    Ping, speed and the share of passed tests each score from 0 to 1 and are
    averaged with their weights. Parts that are not measured are left out and
    the others fill their weight: servers that are not pinged (not TCP) and
    settings without tests cost no points.
    """
    parts = [(SPEED_WEIGHT, min(speed / FULL_SPEED, 1.0))]
    if ping is not None:
        parts.append((PING_WEIGHT, max(1 - ping / (PING_LIMIT * 1000), 0.0)))
    if tests:
        parts.append((TESTS_WEIGHT, sum(tests.values()) / len(tests)))
    return round(100 * sum(weight * score for weight, score in parts) / sum(w for w, _ in parts))


async def test_outbound(
    context: ApplicationContext, server: OutboundServer
) -> OutboundServer | None:
    """Check the server, store ping, speed, rating and tests, and notify clients.

    Not registered as a job or request yet. The core must be started and the
    server registered in it (outbound_register): test_connect only switches the
    test endpoint to a registered server.

    1. TCP servers are pinged, for at most PING_LIMIT seconds. If no attempt
       connects in time, the check stops: speed is None, every test fails, the
       rating is 0 and the server gets filtered = by_ping. Otherwise by_ping
       is cleared.
    2. The test endpoint is switched to the server; checks of different servers
       wait for each other, since the endpoint is shared.
    3. ServerSettings.outbound_tests run at the same time through the endpoint,
       each for at most TEST_TIMEOUT seconds.
    4. Download speed is measured through the endpoint, for at most
       SPEED_TEST_DURATION seconds.

    Returns the stored server, or None if it was deleted during the check.
    Without waiting for the endpoint, the check takes at most about
    PING_LIMIT + TEST_TIMEOUT + SPEED_TEST_DURATION seconds; it does not block
    the event loop.
    """
    outbound_tests = context.settings.server_settings.get().outbound_tests
    tests = {test.alias: False for test in outbound_tests}
    ping = speed = None
    rating = 0
    tcp = uses_tcp(server)
    if tcp:
        ping = await tcp_ping(server.address, server.port)
    if ping is not None or not tcp:
        async with _test_endpoint(context, server.id) as session:
            tests = await _run_tests(session, outbound_tests)
            speed = await download_speed(session)
        rating = server_rating(ping, speed, tests)
    filtered = FilterReason.BY_PING if tcp and ping is None else None
    updated = context.settings.outbound_server.update_health(
        server.id, ping=ping, speed=speed, rating=rating, tests=tests, filtered=filtered
    )
    if updated is not None:
        await context.sync.notify("outbound_server")
    return updated


@long_task("test_outbound_servers", skip_while=["refresh_subscriptions"])
async def test_outbound_servers(context: ApplicationContext) -> None:
    """Check every stored server one after another with test_outbound.

    Runs every hour (main.configure_handlers); can also be awaited directly.
    A long task: skipped while refresh_subscriptions runs, and stopped when a
    refresh starts or the application shuts down. Server ids are taken when
    the run starts: a server deleted or filtered meanwhile is skipped, a changed
    one is checked with its current stored parameters. A failed check is logged
    and the run goes on.

    Filtered servers are skipped, except by_ping ones: they are checked again,
    so a server that answers the ping comes back.

    At the end the checked servers are passed to auto_connect, which may switch
    the connected server; a run stopped midway passes nothing.
    """
    # Imported here: auto_connect checks servers with this module's functions.
    from .auto_connect import on_check_run_finished

    checked = []
    for server_id in [server.id for server in context.settings.outbound_server.get_all()]:
        server = context.settings.outbound_server.get_by_id(server_id)
        if server is None or server.filtered not in (None, FilterReason.BY_PING):
            continue
        try:
            updated = await test_outbound(context, server)
        except Exception:
            log.exception("Failed to check server %s", server_id)
            continue
        if updated is not None:
            checked.append(updated)
    await on_check_run_finished(context, checked)


async def quick_test_outbound(
    context: ApplicationContext, server: OutboundServer, outbound_tests: Sequence[OutboundTest]
) -> OutboundServer:
    """Check the server like test_outbound, without the speed test; nothing is stored.

    Returns the server with the new ping, tests and rating. The rating counts
    the speed of the server's last check (0 if unknown). A TCP server that does
    not answer the ping gets rating 0 and filtered = by_ping, and no test runs;
    otherwise filtered is None. The tests are given by the caller.

    Without waiting for the endpoint, the check takes at most about
    PING_LIMIT + TEST_TIMEOUT seconds.
    """
    tests = {test.alias: False for test in outbound_tests}
    ping = None
    if uses_tcp(server):
        ping = await tcp_ping(server.address, server.port)
        if ping is None:
            return replace(server, ping=None, rating=0, tests=tests, filtered=FilterReason.BY_PING)
    async with _test_endpoint(context, server.id) as session:
        tests = await _run_tests(session, outbound_tests)
    rating = server_rating(ping, server.speed or 0, tests)
    return replace(server, ping=ping, rating=rating, tests=tests, filtered=None)


@asynccontextmanager
async def _test_endpoint(
    context: ApplicationContext, server_id: str
) -> AsyncIterator[ClientSession]:
    """HTTP client through the core's test endpoint, switched to the server.

    Holds outbound_test_lock, so checks of different servers wait for each other;
    the endpoint's traffic is stopped on exit.
    """
    async with context.outbound_test_lock:
        await context.core_client.test_connect(server_id)
        try:
            port = context.core_client.test_port
            if port is None:
                raise RuntimeError("The core has no test endpoint")
            async with proxy_session(port) as session:
                yield session
        finally:
            try:
                await context.core_client.test_stop()
            except Exception:
                # Keep the original error; the next check switches the endpoint anyway.
                log.exception("Failed to stop test traffic")


async def _run_tests(
    session: ClientSession, outbound_tests: Sequence[OutboundTest]
) -> dict[str, bool]:
    """Run the tests at the same time; alias -> passed."""
    results = await asyncio.gather(*(run_test(session, test) for test in outbound_tests))
    return {test.alias: passed for test, passed in zip(outbound_tests, results)}
