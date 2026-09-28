"""JSON representation of models sent to clients; secret fields are never included."""

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import TypeAlias
from uuid import UUID

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

# Field metadata for credentials and raw provider data that may contain them:
# field(default=None, repr=False, metadata=SECRET).
SECRET = MappingProxyType({"secret": True})


def serialize(value: object) -> JsonValue:
    """Convert a dataclass tree to JSON values, omitting fields marked SECRET.

    Datetimes become ISO 8601 strings in UTC with a "Z" suffix.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: serialize(getattr(value, item.name))
            for item in fields(value)
            if not item.metadata.get("secret")
        }
    # StrEnum and IntEnum are also str and int; send their plain values.
    if isinstance(value, Enum):
        return serialize(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("Cannot serialize a naive datetime")
        # ISO 8601 in UTC, e.g. "2026-09-26T12:00:00Z".
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, list | tuple):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if value is None or isinstance(value, bool | int | float | str):
        return value
    raise TypeError(f"Cannot serialize {type(value).__name__}")
