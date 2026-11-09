"""Collections numbered 1..N by priority without gaps: routing rules and subscription links."""

from collections.abc import Sequence
from dataclasses import Field, replace
from typing import Any, ClassVar, Protocol, TypeVar


class PriorityError(ValueError):
    """A priority that is not an integer from 1, or past the end of its collection."""


class Prioritized(Protocol):
    """A frozen dataclass with an id and a priority."""

    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]

    @property
    def id(self) -> str: ...

    @property
    def priority(self) -> int: ...


P = TypeVar("P", bound=Prioritized)


def check_priority(priority: object) -> None:
    """PriorityError unless priority is an integer from 1."""
    if type(priority) is not int or priority < 1:
        raise PriorityError("Priority must be an integer from 1")


def placed(items: Sequence[P], item: P) -> list[P]:
    """The items with item put at its priority, replacing the one with its id.

    The others keep their order and are numbered again: those from that
    priority on move down by one. The priority may be one past the last item
    for a new item; PriorityError if it is further.
    """
    others = [other for other in sorted(items, key=_priority) if other.id != item.id]
    if item.priority > len(others) + 1:
        raise PriorityError(f"Priority must be between 1 and {len(others) + 1}")
    others.insert(item.priority - 1, item)
    return _numbered(others)


def without(items: Sequence[P], item_id: str) -> list[P]:
    """The items without the one with this id; those after it move up by one."""
    return _numbered([item for item in sorted(items, key=_priority) if item.id != item_id])


def _priority(item: Prioritized) -> int:
    return item.priority


def _numbered(items: list[P]) -> list[P]:
    return [
        item if item.priority == number else replace(item, priority=number)
        for number, item in enumerate(items, 1)
    ]
