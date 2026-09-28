"""Application startup handler."""

import logging

from ..models.application_context import ApplicationContext
from .subscriptions import refresh_subscriptions

log = logging.getLogger(__name__)


async def init(context: ApplicationContext) -> None:
    """Refresh stored servers once; the application runs this handler in the background."""
    try:
        await refresh_subscriptions(context)
    except Exception:
        log.exception("Failed to refresh subscription servers at startup")
