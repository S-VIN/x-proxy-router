"""Keep the core in line with the database: registered servers and the connected one."""

import logging

from ..models.application_context import ApplicationContext
from ..models.outbound_server import OutboundServer

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
    A running server check is awaited first, so it is not cut off midway.

    Filtered servers are registered too, and the connected one stays connected
    when it gets filtered: filters only decide which servers the application
    checks and lets clients connect, so changing them does not touch the core.
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
        if connected.id in {server.id for server in servers}:
            try:
                await context.core_client.outbound_connect(connected.id)
                return
            except Exception:
                log.exception("Failed to connect server %s again", connected.id)
        else:
            log.warning("Connected server %s is not registered in the core", connected.id)
        context.settings.outbound_server.set_connected(None)
    await context.sync.notify("outbound_server")


async def connect_outbound_server(
    context: ApplicationContext, server_id: str
) -> OutboundServer | None:
    """Route the core's main traffic through the stored server and remember it.

    The server gets is_connected, the previously connected one loses it, and
    clients are notified. Returns the server, or None if it is not stored.
    Raises ServerFiltered for a filtered server, and CoreError if the core cannot
    switch, e.g. the server was not registered because the core does not support
    its parameters; the previous connection is then kept.
    """
    async with context.core_lock:
        server = context.settings.outbound_server.get_by_id(server_id)
        if server is None:
            return None
        if server.filtered is not None:
            raise ServerFiltered(f"Server {server_id} is filtered: {server.filtered}")
        try:
            await context.core_client.outbound_connect(server_id)
        except Exception as error:
            log.exception("Failed to connect server %s", server_id)
            raise CoreError("The core could not connect to the server") from error
        server = context.settings.outbound_server.set_connected(server_id)
    await context.sync.notify("outbound_server")
    return server
