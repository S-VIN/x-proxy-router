"""A regular expression that filters outbound servers by name."""

import re
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True, kw_only=True)
class RegFilter:
    """Servers whose name matches reg get OutboundServer.filtered = by_reg_filter.

    reg is a Python regular expression found anywhere in the name, case
    sensitive; (?i) at its start ignores case.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    reg: str

    def __post_init__(self):
        if not self.id:
            raise ValueError("Filter id must not be empty")
        if not self.reg:
            raise ValueError("Filter regular expression must not be empty")
        try:
            re.compile(self.reg)
        except re.error as error:
            raise ValueError(f"Invalid regular expression: {error}") from None

    def matches(self, name: str) -> bool:
        # re caches compiled expressions, so repeated reads do not compile again.
        return re.search(self.reg, name) is not None
