"""An HTTP check that outbound servers must pass, configured in ServerSettings."""

from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import uuid4


class OutboundTestRule(StrEnum):
    """Which HTTP status of the response through the server means the test passed."""

    # generate_204 endpoints, e.g. https://www.gstatic.com/generate_204.
    STATUS_204 = "status_204"
    STATUS_2XX = "status_2xx"
    STATUS_BELOW_400 = "status_below_400"
    STATUS_BELOW_500 = "status_below_500"
    STATUS_BELOW_503 = "status_below_503"
    # Any HTTP response: the site is reachable, whatever it answers.
    ANY_STATUS = "any_status"

    def accepts(self, status: int) -> bool:
        match self:
            case OutboundTestRule.STATUS_204:
                return status == 204
            case OutboundTestRule.STATUS_2XX:
                return 200 <= status < 300
            case OutboundTestRule.STATUS_BELOW_400:
                return status < 400
            case OutboundTestRule.STATUS_BELOW_500:
                return status < 500
            case OutboundTestRule.STATUS_BELOW_503:
                return status < 503
            case OutboundTestRule.ANY_STATUS:
                return True


@dataclass(frozen=True, kw_only=True)
class OutboundTest:
    """Clients add and delete tests; a test cannot be changed.

    Clients name a test after its URL's site, so it has no name of its own.
    """

    # Key of OutboundServer.tests.
    id: str = field(default_factory=lambda: str(uuid4()))
    # Requested through each outbound server; not secret. Unique among tests.
    url: str
    rule: OutboundTestRule

    def __post_init__(self):
        if not self.id:
            raise ValueError("Outbound test id must not be empty")
        parts = urlsplit(self.url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("Outbound test URL must be HTTP(S)")
