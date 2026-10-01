"""Errors returned to WebSocket clients, and checks for request payloads."""

from collections.abc import Set as AbstractSet
from enum import StrEnum
from typing import TypeVar

from .models.serialization import JsonValue

T = TypeVar("T", str, int, bool)


class ErrorCode(StrEnum):
    BAD_REQUEST = "bad_request"
    UNKNOWN_REQUEST = "unknown_request"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    SUBSCRIPTION_ERROR = "subscription_error"
    CANCELLED = "cancelled"
    CORE_ERROR = "core_error"
    INTERNAL_ERROR = "internal_error"


class RequestError(Exception):
    """A failed request. Code, message and details are sent to the client as is,
    so they must not contain secrets such as subscription URLs.
    """

    def __init__(self, code: ErrorCode, message: str, details: dict[str, JsonValue] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def expect_fields(
    payload: dict[str, JsonValue],
    required: AbstractSet[str],
    optional: AbstractSet[str] = frozenset(),
) -> None:
    """Reject missing and unknown payload fields with bad_request."""
    if missing := sorted(required - payload.keys()):
        name = missing[0]
        raise RequestError(ErrorCode.BAD_REQUEST, f"Field {name} is required", {"field": name})
    if unknown := sorted(payload.keys() - required - optional):
        name = unknown[0]
        raise RequestError(ErrorCode.BAD_REQUEST, f"Unknown field {name}", {"field": name})


def field_value(payload: dict[str, JsonValue], name: str, kind: type[T]) -> T:
    """Return a payload field of the given JSON type; booleans are not integers."""
    value = payload[name]
    if not isinstance(value, kind) or (isinstance(value, bool) and kind is not bool):
        raise RequestError(
            ErrorCode.BAD_REQUEST, f"Field {name} must be {kind.__name__}", {"field": name}
        )
    return value
