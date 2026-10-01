"""A pattern that filters outbound servers by name."""

from dataclasses import dataclass, field
from uuid import uuid4

from .pattern import pattern_matches


@dataclass(frozen=True, kw_only=True)
class RegFilter:
    """Servers whose name matches reg get OutboundServer.filtered = by_reg_filter.

    reg is a pattern (models/pattern.py) compared with the whole name, ignoring
    case: *RU* finds "🇷🇺 RU Moscow". Any characters are allowed, as in names.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    reg: str

    def __post_init__(self):
        if not self.id:
            raise ValueError("Filter id must not be empty")
        if not self.reg:
            raise ValueError("Filter pattern must not be empty")

    def matches(self, name: str) -> bool:
        return pattern_matches(self.reg, name)
