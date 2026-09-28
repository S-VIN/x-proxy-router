"""Helpers shared by application tests."""

import asyncio

from server.models.application_context import ApplicationContext


async def startup_finished(context: ApplicationContext) -> None:
    """Wait until init's background subscription refresh is over and its messages are queued."""
    async with asyncio.timeout(2):
        while context.tasks.running("refresh_subscriptions") or any(
            task.get_name() == "application-init" for task in asyncio.all_tasks()
        ):
            await asyncio.sleep(0)
    for _ in range(5):
        await asyncio.sleep(0)  # Let connection writers send queued frames.
