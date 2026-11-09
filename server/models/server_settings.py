"""Server-wide settings: a single record for the whole application."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from .serialization import SECRET


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

    outbound_mode: str = "client"
    final_outbound_enabled: bool = False
    final_outbound_uri: str | None = field(default=None, repr=False, metadata=SECRET)
    final_outbound_address: str | None = field(default=None, init=False)

    def __post_init__(self):
        if self.outbound_mode not in ("client", "server"):
            raise ValueError("Outbound mode must be client or server")
        if type(self.final_outbound_enabled) is not bool:
            raise ValueError("Final outbound enabled must be true or false")
        if self.final_outbound_enabled and (
            not self.final_outbound_uri or self.outbound_mode == "server"
        ):
            raise ValueError("Final outbound needs a VLESS link and client mode")
        if self.final_outbound_uri is not None:
            from ..vless import parse_final_outbound

            server = parse_final_outbound(self.final_outbound_uri)
            host = f"[{server.address}]" if ":" in server.address else server.address
            object.__setattr__(self, "final_outbound_address", f"{host}:{server.port}")

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
