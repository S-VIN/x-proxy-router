"""Automatic choice of the connected server: ServerSettings.auto_connect.

The whole algorithm is here; other modules only report events to it:

- on_auto_connect_enabled: a client turned the mode on;
- on_servers_changed: servers were registered in the core again (startup,
  subscription refresh), or a filter was deleted;
- on_check_run_finished: test_outbound_servers checked the servers;
- watch_connected_server: a job every RETRY_INTERVAL seconds (main.py).

Three reasons to replace the connected server, from urgent to optional:

1. Failure. FAILED_CHECKS quick checks in a row fail (about 30 seconds), or a
   full check filters the server by ping. Any working server replaces it at
   once, whatever the limits below.
2. Degradation. The server works, but DEGRADED_CHECKS quick checks in a row
   rate it DEGRADED_DROP points below its score. A server scored MARGIN above
   the quick rating replaces it, if the last switch was MIN_STAY_DEGRADED ago
   and DAILY_SWITCHES are not used up.
3. Improvement. Another server is scored MARGIN above the connected one after
   CONFIRMING_RUNS check runs in a row. It replaces the connected one, if the
   last switch was MIN_STAY_IMPROVEMENT ago and DAILY_SWITCHES are not used up.

A quick check is a check without the speed test (quick_test_outbound): it fails
if a TCP server does not answer the ping, or fewer than half of the tests pass.
Scores are ratings of full checks smoothed over check runs, so one measurement
moves a score by half. Only servers that are not filtered, rated above 0 by
their last check and not in quarantine are chosen, best score first. A server
is checked quickly right before it is connected: one that fails is skipped and
quarantined for CANDIDATE_QUARANTINE. If all tried servers fail, the router's
own connection is taken to be down: nothing changes and nobody is quarantined.
A server left for failing or degrading is quarantined for QUARANTINE, doubled
for each such time within a day, up to MAX_QUARANTINE, so the choice does not
swing between two servers.

When nothing is connected, the best server is connected without limits: at
startup, when a refresh removed the connected server, when the mode is turned
on, and every CHECK_INTERVAL while the mode is on.

State lives in memory (ApplicationContext.auto_connect), keyed by server id,
and is lost on restart. Subscription refreshes change the servers, so every
decision reads the stored servers again, state of servers that are gone is
dropped, and a server is connected only if it is still stored and not filtered
at the moment of the switch.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic

from ..models.application_context import ApplicationContext
from ..models.outbound_server import OutboundServer
from ..models.outbound_test import OutboundTest, OutboundTestRule
from .core import CoreError, switch_connected_server
from .outbound_test import quick_test_outbound

log = logging.getLogger(__name__)

# Seconds between quick checks of the connected server.
CHECK_INTERVAL = 60
# Seconds to the next quick check after a failed one; the watch job runs this often.
RETRY_INTERVAL = 15
# Failed quick checks in a row that make the connected server failed.
FAILED_CHECKS = 3
# Quick checks in a row rated DEGRADED_DROP points below the score that make it degraded.
DEGRADED_CHECKS = 2
DEGRADED_DROP = 20
# Points a server must be ahead to replace a working one.
MARGIN = 10
# Check runs in a row a server must be MARGIN ahead to replace a working one.
CONFIRMING_RUNS = 2
# Weight of the newest full check in a score.
SMOOTHING = 0.5
# Seconds since the last switch before a working server may be replaced.
MIN_STAY_DEGRADED = 15 * 60
MIN_STAY_IMPROVEMENT = 60 * 60
# Switches for degradation and improvement within the last DAY seconds.
DAILY_SWITCHES = 4
DAY = 24 * 60 * 60
# Seconds a server left for failing or degrading is not chosen; doubled for
# each such time within a day.
QUARANTINE = 30 * 60
MAX_QUARANTINE = 4 * 60 * 60
# Seconds a server that failed its check before connecting is not chosen.
CANDIDATE_QUARANTINE = 10 * 60
# Servers checked before connecting, at most, per decision.
CANDIDATES_TRIED = 3
# Quick checks run it when there are no outbound tests, so they check the proxy
# itself, not only the ping.
REACHABILITY_TEST = OutboundTest(
    id="reachability",
    url="https://www.gstatic.com/generate_204",
    rule=OutboundTestRule.STATUS_204,
)


class Reason(StrEnum):
    """Why a server is connected; written to the log."""

    NOTHING_CONNECTED = "nothing was connected"
    ENABLED = "auto connect was turned on"
    FAILURE = "the connected server failed"
    DEGRADATION = "the connected server degraded"
    IMPROVEMENT = "a better server was found"


# Switches counted towards DAILY_SWITCHES.
_LIMITED = {Reason.DEGRADATION, Reason.IMPROVEMENT}
# The server left for these reasons is quarantined.
_PUNISHED = {Reason.FAILURE, Reason.DEGRADATION}


@dataclass
class AutoConnectState:
    """What the algorithm remembers between events; times are monotonic()."""

    # One decision at a time; core_lock is taken only for the switch itself.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Server id -> smoothed rating of full checks.
    scores: dict[str, float] = field(default_factory=dict)
    # Server id -> time until which it is not chosen.
    quarantine: dict[str, float] = field(default_factory=dict)
    # Server id -> times it was left for failing or degrading.
    strikes: dict[str, list[float]] = field(default_factory=dict)
    # Server id -> check runs in a row that scored it MARGIN above the connected one.
    better_runs: dict[str, int] = field(default_factory=dict)
    # Times of switches counted towards DAILY_SWITCHES.
    switches: list[float] = field(default_factory=list)
    # Time of the last switch made here.
    last_switch: float | None = None
    # The server quick checks watch and their results in a row.
    watched: str | None = None
    failures: int = 0
    degradations: int = 0
    # When the next quick check is due, or the next try while nothing is connected.
    next_check: float = 0.0


async def on_auto_connect_enabled(context: ApplicationContext) -> None:
    """A client turned the mode on: choose a server now.

    With nothing connected, the best server is connected. A connected server
    filtered by ping is replaced by any; another one stays unless a server is
    scored MARGIN above it. Quick checks and check runs are counted anew.
    """
    state = context.auto_connect
    async with state.lock:
        if not _enabled(context):
            return
        connected = context.settings.outbound_server.get_connected()
        _watch(state, connected.id if connected is not None else None, monotonic())
        state.better_runs.clear()
        if connected is None:
            await _connect_best(context, None, Reason.NOTHING_CONNECTED)
        elif connected.filtered is not None:
            await _connect_best(context, connected, Reason.FAILURE)
        else:
            above = _score(state, connected) + MARGIN
            await _connect_best(context, connected, Reason.ENABLED, above=above)


async def on_servers_changed(context: ApplicationContext) -> None:
    """Servers were registered in the core again, or a filter was deleted.

    Forgets servers that are gone. With the mode on, connects the best server if
    nothing is connected, e.g. the refresh removed the connected one, and
    replaces a connected server filtered by ping.
    """
    state = context.auto_connect
    async with state.lock:
        servers = context.settings.outbound_server.get_all()
        _forget_missing(state, servers)
        if not _enabled(context):
            return
        connected = next((server for server in servers if server.is_connected), None)
        if connected is None:
            await _connect_best(context, None, Reason.NOTHING_CONNECTED)
        elif connected.filtered is not None:
            await _connect_best(context, connected, Reason.FAILURE)


async def on_check_run_finished(
    context: ApplicationContext, checked: Sequence[OutboundServer]
) -> None:
    """test_outbound_servers checked these servers; they carry the stored results.

    Their scores take in the new ratings, whether the mode is on or not. With
    the mode on: nothing connected, the best server is connected; the connected
    server filtered by ping is replaced (failure). Otherwise every server scored
    MARGIN above the connected one counts one more run in a row, and the best
    of those with CONFIRMING_RUNS replaces it (improvement), within the limits.
    """
    state = context.auto_connect
    async with state.lock:
        for server in checked:
            _record(state, server)
        servers = context.settings.outbound_server.get_all()
        _forget_missing(state, servers)
        if not _enabled(context):
            return
        connected = next((server for server in servers if server.is_connected), None)
        if connected is None:
            await _connect_best(context, None, Reason.NOTHING_CONNECTED)
            return
        if connected.filtered is not None:
            await _connect_best(context, connected, Reason.FAILURE)
            return
        now = monotonic()
        above = _score(state, connected) + MARGIN
        ahead = [
            server for server in _candidates(state, servers, now) if _score(state, server) >= above
        ]
        state.better_runs = {server.id: state.better_runs.get(server.id, 0) + 1 for server in ahead}
        confirmed = [server for server in ahead if state.better_runs[server.id] >= CONFIRMING_RUNS]
        if confirmed and _may_switch(state, now, MIN_STAY_IMPROVEMENT):
            await _switch(context, connected, confirmed, Reason.IMPROVEMENT)


async def watch_connected_server(context: ApplicationContext) -> None:
    """Quick checks of the connected server; a job every RETRY_INTERVAL seconds.

    Does nothing while the mode is off or subscriptions are refreshed, and until
    a check is due: CHECK_INTERVAL after the last one, RETRY_INTERVAL after a
    failed one. When nothing is connected, the best server is connected instead.
    """
    state = context.auto_connect
    if not _enabled(context) or context.tasks.running("refresh_subscriptions"):
        return
    async with state.lock:
        now = monotonic()
        if not _enabled(context) or now < state.next_check:
            return
        connected = context.settings.outbound_server.get_connected()
        if connected is None:
            await _connect_best(context, None, Reason.NOTHING_CONNECTED)
            return
        if connected.id != state.watched:
            _watch(state, connected.id, now)
        if connected.filtered is not None:
            # Filtered by ping by a full check: it failed already.
            state.next_check = now + CHECK_INTERVAL
            await _connect_best(context, connected, Reason.FAILURE)
            return
        result = await _quick_check(context, connected)
        now = monotonic()
        if not _enabled(context) or _connected_id(context) != connected.id:
            return  # A client or a refresh changed the choice meanwhile.
        if result is None or not _passed(result):
            state.failures += 1
            state.degradations = 0
            state.next_check = now + RETRY_INTERVAL
            if state.failures >= FAILED_CHECKS:
                # If no server works, the failed one is tried again at the usual pace.
                state.next_check = now + CHECK_INTERVAL
                await _connect_best(context, connected, Reason.FAILURE)
            return
        state.failures = 0
        state.next_check = now + CHECK_INTERVAL
        rating = result.rating or 0
        if rating < _score(state, connected) - DEGRADED_DROP:
            state.degradations += 1
        else:
            state.degradations = 0
        if state.degradations >= DEGRADED_CHECKS and _may_switch(state, now, MIN_STAY_DEGRADED):
            above = rating + MARGIN
            if not await _connect_best(context, connected, Reason.DEGRADATION, above=above):
                state.degradations = 0  # Counted anew before the next try.


async def _connect_best(
    context: ApplicationContext,
    current: OutboundServer | None,
    reason: Reason,
    *,
    above: float = 0,
) -> bool:
    """Connect the best server scored at least `above` instead of current; see _switch."""
    state = context.auto_connect
    servers = context.settings.outbound_server.get_all()
    candidates = [
        server
        for server in _candidates(state, servers, monotonic())
        if _score(state, server) >= above
    ]
    return await _switch(context, current, candidates, reason)


async def _switch(
    context: ApplicationContext,
    current: OutboundServer | None,
    candidates: Sequence[OutboundServer],
    reason: Reason,
) -> bool:
    """Connect the first candidate that passes a quick check instead of current.

    At most CANDIDATES_TRIED candidates are checked. Those that fail, or that the
    core cannot connect, are quarantined for CANDIDATE_QUARANTINE, but only if
    another one is connected. The switch is made under core_lock, only if the
    mode is still on and current is still connected; a candidate deleted or
    filtered meanwhile is skipped. Returns whether a server was connected.
    If nothing is connected and stays so, the watch tries again in CHECK_INTERVAL.
    """
    state = context.auto_connect
    current_id = current.id if current is not None else None
    failed = []
    connected = None
    for candidate in candidates[:CANDIDATES_TRIED]:
        result = await _quick_check(context, candidate)
        if result is None or not _passed(result):
            failed.append(candidate.id)
            continue
        async with context.core_lock:
            if not _enabled(context) or _connected_id(context) != current_id:
                return False
            stored = context.settings.outbound_server.get_by_id(candidate.id)
            if stored is None or stored.filtered is not None:
                continue
            try:
                connected = await switch_connected_server(context, candidate.id)
            except CoreError:
                failed.append(candidate.id)
                continue
        break
    now = monotonic()
    if connected is None:
        if current is None:
            state.next_check = now + CHECK_INTERVAL
        return False
    for server_id in failed:
        state.quarantine[server_id] = max(
            state.quarantine.get(server_id, 0), now + CANDIDATE_QUARANTINE
        )
    if current_id is not None and reason in _PUNISHED:
        _strike(state, current_id, now)
    if reason in _LIMITED:
        state.switches.append(now)
    state.last_switch = now
    state.better_runs.clear()
    _watch(state, connected.id, now + CHECK_INTERVAL)
    log.info("Auto connect: server %s replaces %s: %s", connected.id, current_id, reason)
    await context.sync.notify("outbound_server")
    return True


async def _quick_check(
    context: ApplicationContext, server: OutboundServer
) -> OutboundServer | None:
    """quick_test_outbound with the outbound tests, or REACHABILITY_TEST if there are none.

    None if the check itself fails, e.g. the core cannot switch its test endpoint.
    """
    tests = context.settings.outbound_test.get_all() or [REACHABILITY_TEST]
    try:
        return await quick_test_outbound(context, server, tests)
    except Exception:
        log.exception("Failed to check server %s", server.id)
        return None


def _passed(result: OutboundServer) -> bool:
    """The server answered the ping, if pinged, and passed at least half of the tests."""
    if result.filtered is not None:
        return False
    tests = result.tests or {}
    return 2 * sum(tests.values()) >= len(tests)


def _candidates(
    state: AutoConnectState, servers: Sequence[OutboundServer], now: float
) -> list[OutboundServer]:
    """Servers that may replace the connected one, best score first.

    Not connected, not filtered, rated above 0 by the last check, not in
    quarantine. Servers with equal scores keep their stored order.
    """
    allowed = [
        server
        for server in servers
        if not server.is_connected
        and server.filtered is None
        and (server.rating or 0) > 0
        and state.quarantine.get(server.id, 0) <= now
    ]
    return sorted(allowed, key=lambda server: _score(state, server), reverse=True)


def _score(state: AutoConnectState, server: OutboundServer) -> float:
    """Smoothed rating; the stored rating until a check run is seen; 0 if unchecked."""
    return state.scores.get(server.id, server.rating or 0)


def _record(state: AutoConnectState, server: OutboundServer) -> None:
    """Take a full check's rating into the server's score."""
    if server.rating is None:
        return
    score = state.scores.get(server.id)
    state.scores[server.id] = (
        server.rating if score is None else SMOOTHING * server.rating + (1 - SMOOTHING) * score
    )


def _forget_missing(state: AutoConnectState, servers: Sequence[OutboundServer]) -> None:
    """Drop what is remembered about servers no longer stored."""
    ids = {server.id for server in servers}
    for remembered in (state.scores, state.quarantine, state.strikes, state.better_runs):
        for server_id in remembered.keys() - ids:
            del remembered[server_id]


def _strike(state: AutoConnectState, server_id: str, now: float) -> None:
    """Quarantine a server left for failing or degrading; longer for each time within a day."""
    strikes = [time for time in state.strikes.get(server_id, []) if now - time < DAY]
    strikes.append(now)
    state.strikes[server_id] = strikes
    duration = min(QUARANTINE * 2 ** (len(strikes) - 1), MAX_QUARANTINE)
    state.quarantine[server_id] = max(state.quarantine.get(server_id, 0), now + duration)


def _may_switch(state: AutoConnectState, now: float, min_stay: float) -> bool:
    """The last switch was min_stay seconds ago or more, and DAILY_SWITCHES are not used up."""
    state.switches = [time for time in state.switches if now - time < DAY]
    if state.last_switch is not None and now - state.last_switch < min_stay:
        return False
    return len(state.switches) < DAILY_SWITCHES


def _watch(state: AutoConnectState, server_id: str | None, next_check: float) -> None:
    """Count quick checks of this server anew, starting at next_check."""
    state.watched = server_id
    state.failures = state.degradations = 0
    state.next_check = next_check


def _enabled(context: ApplicationContext) -> bool:
    return context.settings.server_settings.get().auto_connect


def _connected_id(context: ApplicationContext) -> str | None:
    connected = context.settings.outbound_server.get_connected()
    return connected.id if connected is not None else None
