"""A rule that decides where the inbounds' traffic to an address goes, independent of the core."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from uuid import uuid4

from .pattern import WILDCARD


class RoutingAction(StrEnum):
    # Through the connected server; blocked while none is connected.
    PROXY = "proxy"
    # Straight from this computer, without a server.
    DIRECT = "direct"
    # The connection is closed at once.
    BLOCK = "block"


_DOMAIN = re.compile(r"[a-z0-9._*-]+")
# Leading whole octets, each followed by a dot, then the wildcard: 192.168.*
_IPV4_PREFIX = re.compile(r"((?:\d{1,3}\.){1,3})\*")
_IPV4_ERROR = "In an IP pattern * replaces whole octets at the end, e.g. 192.168.*"


class RoutingRuleFieldError(ValueError):
    """An invalid value of one field; field names it for clients."""

    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, kw_only=True)
class RoutingRule:
    """Traffic to an address matching reg takes action; the first match by priority wins.

    reg is a pattern (models/pattern.py) of the destination as the application
    sent it, one of:
    - a domain pattern of Latin letters, digits, -, _, . and *: *.youtube.com;
    - an IPv4 address, or its leading whole octets followed by *: 192.168.*;
    - an IPv6 address, exact only;
    - * alone, for every destination.
    Domain patterns never match IP addresses and IP patterns never match
    domains: a domain is not resolved for the rules.
    Construction normalizes reg: lower case, ** as *, IPv6 in compressed form.
    Traffic no rule matches goes through the connected server, as with proxy.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    # 1 is checked first; the rules of a collection are numbered 1..N without gaps.
    priority: int
    reg: str
    action: RoutingAction

    def __post_init__(self):
        if not self.id:
            raise RoutingRuleFieldError("Rule id must not be empty", "id")
        if type(self.priority) is not int or self.priority < 1:
            raise RoutingRuleFieldError("Priority must be an integer from 1", "priority")
        if not isinstance(self.action, RoutingAction):
            raise RoutingRuleFieldError("Unknown action", "action")
        object.__setattr__(self, "reg", _normalized(self.reg))

    @property
    def network(self) -> IPv4Network | IPv6Network | None:
        """The addresses an IP pattern stands for; None for domain patterns and *."""
        return _network(self.reg)


def _normalized(reg: object) -> str:
    if not isinstance(reg, str) or not reg:
        raise RoutingRuleFieldError("Pattern must not be empty", "reg")
    reg = re.sub(r"\*{2,}", WILDCARD, reg.lower())
    if ":" in reg:
        # Only an exact IPv6 address: its parts are not split by dots like octets.
        try:
            address = ip_address(reg)
        except ValueError:
            address = None
        if not isinstance(address, IPv6Address) or address.scope_id is not None:
            raise RoutingRuleFieldError("An IPv6 pattern must be an exact address", "reg")
        return address.compressed
    _network(reg)
    if not _DOMAIN.fullmatch(reg):
        raise RoutingRuleFieldError(
            "A domain pattern may contain only Latin letters, digits, -, _, . and *", "reg"
        )
    return reg


def _network(reg: str) -> IPv4Network | IPv6Network | None:
    """The network of an IP pattern; RoutingRuleFieldError for an IPv4 pattern of another form.

    Patterns of digits, dots and * with at least one digit are IPv4 patterns:
    no domain ends with a numeric label.
    """
    if reg == WILDCARD:
        return None
    if ":" in reg:
        return ip_network(reg)
    if not re.fullmatch(r"[\d.*]*\d[\d.*]*", reg):
        return None
    prefix = _IPV4_PREFIX.fullmatch(reg)
    try:
        if prefix is None:
            return IPv4Network(IPv4Address(reg))
        octets = prefix[1].split(".")[:-1]
        if any(str(int(octet)) != octet for octet in octets):
            raise ValueError("Leading zeros")
        return IPv4Network(".".join(octets + ["0"] * (4 - len(octets))) + f"/{8 * len(octets)}")
    except ValueError:
        raise RoutingRuleFieldError(_IPV4_ERROR, "reg") from None


def placed(rules: Sequence[RoutingRule], rule: RoutingRule) -> list[RoutingRule]:
    """The rules with rule put at its priority, replacing the one with its id.

    The others keep their order and are numbered again: those from that
    priority on move down by one. The priority may be one past the last rule
    for a new rule; RoutingRuleFieldError if it is further.
    """
    others = [other for other in sorted(rules, key=_priority) if other.id != rule.id]
    if rule.priority > len(others) + 1:
        raise RoutingRuleFieldError(f"Priority must be between 1 and {len(others) + 1}", "priority")
    others.insert(rule.priority - 1, rule)
    return _numbered(others)


def without(rules: Sequence[RoutingRule], rule_id: str) -> list[RoutingRule]:
    """The rules without the one with this id; those after it move up by one."""
    return _numbered([rule for rule in sorted(rules, key=_priority) if rule.id != rule_id])


def _priority(rule: RoutingRule) -> int:
    return rule.priority


def _numbered(rules: list[RoutingRule]) -> list[RoutingRule]:
    return [
        rule if rule.priority == number else replace(rule, priority=number)
        for number, rule in enumerate(rules, 1)
    ]
