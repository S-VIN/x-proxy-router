"""Keep the core in line with the database: registered servers and the connected one."""

import logging
from dataclasses import replace

from ..models.application_context import ApplicationContext
from ..models.outbound_server import FilterReason, OutboundServer

log = logging.getLogger(__name__)


class CoreError(Exception):
    """The core rejected a change. The message is safe to send to clients."""


class ServerFiltered(Exception):
    """The server is filtered (OutboundServer.filtered), so it cannot be connected."""


async def register_outbound_servers(context: ApplicationContext) -> None:
    """Replace the servers registered in the core with the stored ones.

    Servers the core cannot use are skipped and logged, so one of them does not
    keep the others out. outbound_register blocks both routes; the main route is
    then connected again to the server with is_connected. If that server was
    not registered or the core cannot connect to it, its is_connected is cleared.
    A server filtered by name is not connected again either, and auto_connect is
    turned off, as in disconnect_filtered_server.
    A running server check is awaited first, so it is not cut off midway.

    Filtered servers are registered too: filters only decide which servers the
    application checks and connects. A connected server filtered by ping stays
    connected.
    """
    servers = []
    for server in context.settings.outbound_server.get_all():
        try:
            context.core_client.check_outbound_server_config(server)
        except ValueError:
            # The error may quote provider settings, so only the id is logged.
            log.warning("Server %s is not supported by the core and is not registered", server.id)
            continue
        servers.append(server)
    async with context.outbound_test_lock, context.core_lock:
        await context.core_client.outbound_register(servers)
        connected = context.settings.outbound_server.get_connected()
        if connected is None:
            return
        if connected.filtered == FilterReason.BY_REG_FILTER:
            # The route is blocked already by outbound_register.
            log.info("Connected server %s is filtered by name and is disconnected", connected.id)
            _turn_auto_connect_off(context)
        elif connected.id in {server.id for server in servers}:
            try:
                await context.core_client.outbound_connect(connected.id)
                return
            except Exception:
                log.exception("Failed to connect server %s again", connected.id)
        else:
            log.warning("Connected server %s is not registered in the core", connected.id)
        context.settings.outbound_server.set_connected(None)
    await context.sync.notify("server_settings")
    await context.sync.notify("outbound_server")


async def connect_outbound_server(
    context: ApplicationContext, server_id: str
) -> OutboundServer | None:
    """Route the core's main traffic through the server a client chose, and remember it.

    The server gets is_connected, the previously connected one loses it. The
    choice turns ServerSettings.auto_connect off, so the server no longer
    switches by itself; clients get server_settings, then outbound_server.
    Returns the server, or None if it is not stored.
    Raises ServerFiltered for a filtered server, and CoreError if the core cannot
    switch, e.g. the server was not registered because the core does not support
    its parameters; the previous connection and auto_connect are then kept.
    """
    async with context.core_lock:
        server = context.settings.outbound_server.get_by_id(server_id)
        if server is None:
            return None
        if server.filtered is not None:
            raise ServerFiltered(f"Server {server_id} is filtered: {server.filtered}")
        server = await _switch(context, server_id)
        # Under the lock, so auto_connect cannot replace the chosen server meanwhile.
        _turn_auto_connect_off(context)
    await context.sync.notify("server_settings")
    await context.sync.notify("outbound_server")
    return server


async def disconnect_filtered_server(context: ApplicationContext) -> None:
    """Disconnect the connected server if its name matches a filter.

    The core's main route is blocked, is_connected is cleared and auto_connect is
    turned off, so nothing is connected until a client chooses a server or turns
    the mode on. Clients get server_settings, then outbound_server. If the core
    fails, the error is logged and the server is marked disconnected anyway.
    A connected server filtered by ping stays connected.
    """
    async with context.core_lock:
        connected = context.settings.outbound_server.get_connected()
        if connected is None or connected.filtered != FilterReason.BY_REG_FILTER:
            return
        try:
            await context.core_client.outbound_disconnect()
        except Exception:
            log.exception("Failed to disconnect filtered server %s", connected.id)
        context.settings.outbound_server.set_connected(None)
        _turn_auto_connect_off(context)
    await context.sync.notify("server_settings")
    await context.sync.notify("outbound_server")


def _turn_auto_connect_off(context: ApplicationContext) -> None:
    """Save auto_connect = False; the caller notifies server_settings."""
    settings = context.settings.server_settings.get()
    if settings.auto_connect:
        context.settings.server_settings.save(replace(settings, auto_connect=False))


def _rating(server: OutboundServer) -> int:
    """Rating for choosing a server: an unchecked one (None) counts as 0."""
    return server.rating or 0


async def connect_best_outbound_server(context: ApplicationContext) -> None:
    """With ServerSettings.auto_connect on, connect the server with the best rating.

    Only servers that are not filtered and rated above 0 are chosen. The connected
    server stays unless another one is rated higher, so servers with equal ratings
    do not take turns; a connected server filtered by ping is replaced by any such
    server (one filtered by name is disconnected: disconnect_filtered_server).
    If the core cannot connect a server, the next best is tried; failures are only
    logged. Nothing changes when the mode is off or no server is better.

    Runs when a client turns the mode on and whenever ratings, servers or filters
    change: after a check run, a subscription refresh, startup and a filter deletion.
    """
    async with context.core_lock:
        # Read under the lock: a client that connected a server meanwhile turned it off.
        if not context.settings.server_settings.get().auto_connect:
            return
        servers = context.settings.outbound_server.get_all()
        connected = next((server for server in servers if server.is_connected), None)
        floor = _rating(connected) if connected is not None and connected.filtered is None else 0
        better = [
            server for server in servers if server.filtered is None and _rating(server) > floor
        ]
        # Stable: servers with equal ratings keep their stored order.
        for server in sorted(better, key=_rating, reverse=True):
            try:
                await _switch(context, server.id)
            except CoreError:
                continue
            break
        else:
            return
    await context.sync.notify("outbound_server")


async def _switch(context: ApplicationContext, server_id: str) -> OutboundServer | None:
    """Connect the core's main route to a stored server and mark it; hold core_lock.

    Raises CoreError if the core cannot connect it; nothing is marked then.
    """
    try:
        await context.core_client.outbound_connect(server_id)
    except Exception as error:
        log.exception("Failed to connect server %s", server_id)
        raise CoreError("The core could not connect to the server") from error
    return context.settings.outbound_server.set_connected(server_id)
