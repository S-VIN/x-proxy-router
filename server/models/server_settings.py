"""Server-wide settings: a single record for the whole application."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


@dataclass(frozen=True, kw_only=True)
class ServerSettings:
    # Only one record exists, so the id is fixed and cannot be passed in.
    id: Literal[0] = field(default=0, init=False)
    # Seconds between automatic subscription refreshes.
    subscription_refresh_interval: int = 24 * 60 * 60
    # None until subscriptions are refreshed for the first time.
    last_subscription_refresh: datetime | None = None
    # The server chooses the connected server itself (handlers/auto_connect.py).
    # Turned off when a client connects a server itself.
    auto_connect: bool = False

    def __post_init__(self):
        interval = self.subscription_refresh_interval
        if type(interval) is not int or interval <= 0:
            raise ValueError("Subscription refresh interval must be a positive number of seconds")
        if type(self.auto_connect) is not bool:
            raise ValueError("Auto connect must be true or false")
        refreshed = self.last_subscription_refresh
        if refreshed is not None:
            if refreshed.utcoffset() is None:
                raise ValueError("Last subscription refresh must be timezone-aware")
            object.__setattr__(self, "last_subscription_refresh", refreshed.astimezone(UTC))
