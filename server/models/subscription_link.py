"""A subscription URL and its stable application identifier."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import uuid4

from .serialization import SECRET


@dataclass(frozen=True, kw_only=True)
class SubscriptionLink:
    # Access URLs usually embed a provider token.
    url: str = field(repr=False, metadata=SECRET)
    id: str = field(default_factory=lambda: str(uuid4()))
    # Derived from url on every construction and replace(), never stored:
    # scheme and host only, e.g. "https://sub.example.com", safe to show to clients.
    url_short: str = field(init=False)

    def __post_init__(self):
        parts = urlsplit(self.url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("Subscription URL must be HTTP(S)")
        if not self.id:
            raise ValueError("Subscription id must not be empty")
        # hostname drops credentials and the port; IPv6 needs its brackets back.
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        object.__setattr__(self, "url_short", f"{parts.scheme}://{host}")
