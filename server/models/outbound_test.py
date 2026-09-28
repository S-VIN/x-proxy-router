"""An HTTP check that outbound servers must pass, configured in ServerSettings."""

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


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
    # Requested through each outbound server; not secret, clients edit it.
    url: str
    # Unique within ServerSettings.outbound_tests; key of OutboundServer.tests.
    alias: str
    rule: OutboundTestRule

    def __post_init__(self):
        parts = urlsplit(self.url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("Outbound test URL must be HTTP(S)")
        if not self.alias.strip():
            raise ValueError("Outbound test alias must not be empty")
