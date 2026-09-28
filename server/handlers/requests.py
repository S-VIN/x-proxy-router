"""Client requests of type "request": actions rather than changes of one model."""

from ..models.application_context import ApplicationContext
from ..models.serialization import JsonValue
from ..request_error import ErrorCode, RequestError, expect_fields, field_value
from ..subscription_loader import SubscriptionError
from .core import CoreError, ServerFiltered, connect_outbound_server
from .outbound_test import test_outbound_servers
from .subscriptions import refresh_subscriptions


async def request_refresh_subscriptions(
    context: ApplicationContext, payload: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """payload: {}. Reload all subscriptions now instead of waiting for the timer.

    If a refresh is already running, no new one starts: the response comes when
    the running one finishes, with its result.
    """
    expect_fields(payload, set())
    try:
        await refresh_subscriptions(context)
    except SubscriptionError as error:
        raise RequestError(
            ErrorCode.SUBSCRIPTION_ERROR,
            "Subscriptions could not be loaded",
            {"failed_id": error.subscription_id},
        ) from None
    return {}


async def request_test_outbound_servers(
    context: ApplicationContext, payload: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """payload: {}. Check servers now; responds when the whole run is over.

    Each server's results reach clients as soon as it is checked. Filtered
    servers are skipped, except by_ping ones. If a run is already going, the
    response comes when it ends. While subscriptions are refreshed nothing is
    checked: conflict.
    """
    expect_fields(payload, set())
    # No await before the call, so the refresh cannot start in between.
    if context.tasks.running("refresh_subscriptions"):
        raise RequestError(
            ErrorCode.CONFLICT, "Servers are not checked while subscriptions are refreshed"
        )
    await test_outbound_servers(context)
    return {}


async def request_connect_outbound_server(
    context: ApplicationContext, payload: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """payload: {id}. Route the core's main traffic through this server.

    A filtered server gives conflict; the connection is not changed.
    """
    expect_fields(payload, {"id"})
    server_id = field_value(payload, "id", str)
    try:
        server = await connect_outbound_server(context, server_id)
    except ServerFiltered:
        raise RequestError(
            ErrorCode.CONFLICT, "Filtered servers cannot be connected", {"id": server_id}
        ) from None
    except CoreError as error:
        raise RequestError(ErrorCode.CORE_ERROR, str(error), {"id": server_id}) from None
    if server is None:
        raise RequestError(ErrorCode.NOT_FOUND, "Outbound server not found", {"field": "id"})
    return {}
