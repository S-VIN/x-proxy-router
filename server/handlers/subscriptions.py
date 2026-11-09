"""Subscription handlers independent of timers and WebSocket messages."""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial

from apscheduler.triggers.interval import IntervalTrigger

from ..models.application_context import ApplicationContext
from ..models.inbound_server import InboundServer, InboundType
from ..models.outbound_server import OutboundServer
from ..models.subscription_link import SubscriptionLink
from ..subscription_loader import SubscriptionError, load_subscription
from ..tasks import long_task
from .auto_connect import on_servers_changed
from .core import register_outbound_servers

log = logging.getLogger(__name__)


@long_task("refresh_subscriptions", cancels=["test_outbound_servers"])
async def refresh_subscriptions(context: ApplicationContext) -> None:
    """Replace stored servers with all subscriptions' servers and send changes to clients.

    Each subscription is loaded directly first, then through the main inbound
    (_load_subscription). On success server_settings.last_subscription_refresh is
    set to the current time, and the stored servers are registered in the core
    again: both of its routes become blocked (see register_outbound_servers).
    With auto_connect on, the best server is connected then if nothing is, e.g.
    when the connected one is gone (auto_connect.on_servers_changed).

    A long task: a running test_outbound_servers is stopped first. If a refresh
    is already running, no new one starts and the caller waits for the running one.
    If any subscription fails to load, the stored servers and the refresh time are
    kept and SubscriptionError is raised.
    """
    servers: list[OutboundServer] = []
    for link in context.settings.subscription_link.get_all():
        servers.extend(await _load_subscription(context, link))
    context.settings.outbound_server.update_servers(servers)
    await context.sync.notify("outbound_server")
    settings = context.settings.server_settings.get()
    refreshed = replace(settings, last_subscription_refresh=datetime.now(UTC))
    context.settings.server_settings.save(refreshed)
    await context.sync.notify("server_settings")
    # Last, so the database and clients are up to date even if the core fails.
    await register_outbound_servers(context)
    await on_servers_changed(context)


async def _load_subscription(
    context: ApplicationContext, link: SubscriptionLink
) -> list[OutboundServer]:
    """Load a subscription directly; if that fails, again through the main inbound.

    A provider may be blocked on this computer's network but reachable through
    the connected server. The second attempt follows the routing rules like any
    traffic of the inbound. Without it (see _main_inbound) the first error is raised.
    """
    try:
        return await load_subscription(link)
    except SubscriptionError:
        inbound = _main_inbound(context)
        if inbound is None:
            raise
    log.info("Subscription %s did not load directly, retrying through the inbound", link.id)
    return await load_subscription(link, inbound)


def _main_inbound(context: ApplicationContext) -> InboundServer | None:
    """The first stored inbound if it is an enabled, listening proxy and a server is connected."""
    inbounds = context.settings.inbound_server.get_all()
    if not inbounds or context.settings.outbound_server.get_connected() is None:
        return None
    inbound = inbounds[0]
    if inbound.type != InboundType.PROXY or not inbound.enabled or inbound.error is not None:
        return None
    return inbound


def schedule_refresh_subscriptions(context: ApplicationContext) -> None:
    """Run refresh_subscriptions every subscription_refresh_interval seconds, counting from now.

    Adds the "refresh_subscriptions" job, or restarts its timer with the current
    interval if it exists. Refreshes started otherwise do not move the schedule.
    """
    interval = context.settings.server_settings.get().subscription_refresh_interval
    trigger = IntervalTrigger(seconds=interval)
    if context.scheduler.get_job("refresh_subscriptions") is None:
        context.scheduler.add_job(
            partial(refresh_subscriptions, context), trigger, id="refresh_subscriptions"
        )
    else:
        context.scheduler.reschedule_job("refresh_subscriptions", trigger)
