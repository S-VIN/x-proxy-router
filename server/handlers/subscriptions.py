"""Subscription handlers independent of timers and WebSocket messages."""

from dataclasses import replace
from datetime import UTC, datetime
from functools import partial

from apscheduler.triggers.interval import IntervalTrigger

from ..models.application_context import ApplicationContext
from ..models.outbound_server import OutboundServer
from ..subscription_loader import load_subscription
from ..tasks import long_task
from .core import register_outbound_servers


@long_task("refresh_subscriptions", cancels=["test_outbound_servers"])
async def refresh_subscriptions(context: ApplicationContext) -> None:
    """Replace stored servers with all subscriptions' servers and send changes to clients.

    On success server_settings.last_subscription_refresh is set to the current time,
    and the stored servers are registered in the core again: both of its routes
    become blocked (see register_outbound_servers).

    A long task: a running test_outbound_servers is stopped first. If a refresh
    is already running, no new one starts and the caller waits for the running one.
    If any subscription fails to load, the stored servers and the refresh time are
    kept and SubscriptionError is raised.
    """
    servers: list[OutboundServer] = []
    for link in context.settings.subscription_link.get_all():
        servers.extend(await load_subscription(link))
    context.settings.outbound_server.update_servers(servers)
    await context.sync.notify("outbound_server")
    settings = context.settings.server_settings.get()
    refreshed = replace(settings, last_subscription_refresh=datetime.now(UTC))
    context.settings.server_settings.save(refreshed)
    await context.sync.notify("server_settings")
    # Last, so the database and clients are up to date even if the core fails.
    await register_outbound_servers(context)


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
