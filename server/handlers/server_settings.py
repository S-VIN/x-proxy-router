"""Client requests that change the server-wide settings."""

from dataclasses import replace

from ..models.application_context import ApplicationContext
from ..models.serialization import JsonValue
from ..request_error import ErrorCode, RequestError, expect_fields, field_value
from .auto_connect import on_auto_connect_enabled
from .subscriptions import schedule_refresh_subscriptions

MODEL = "server_settings"


async def change_server_settings(
    context: ApplicationContext, payload: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """payload: {id: 0, subscription_refresh_interval?, auto_connect?}.

    A new interval restarts the refresh timer, counting from now. auto_connect
    turned from false to true chooses a server before the response
    (auto_connect.on_auto_connect_enabled).
    last_subscription_refresh is maintained by the server and cannot be changed.
    """
    expect_fields(payload, {"id"}, {"subscription_refresh_interval", "auto_connect"})
    if field_value(payload, "id", int) != 0:
        raise RequestError(ErrorCode.NOT_FOUND, "Server settings have id 0", {"field": "id"})
    settings = context.settings.server_settings.get()
    changes = {}
    if "subscription_refresh_interval" in payload:
        changes["subscription_refresh_interval"] = field_value(
            payload, "subscription_refresh_interval", int
        )
    if "auto_connect" in payload:
        changes["auto_connect"] = field_value(payload, "auto_connect", bool)
    interval, was_on = settings.subscription_refresh_interval, settings.auto_connect
    settings = replace(settings, **changes)
    context.settings.server_settings.save(settings)
    await context.sync.notify(MODEL)
    if settings.subscription_refresh_interval != interval:
        schedule_refresh_subscriptions(context)
    if settings.auto_connect and not was_on:
        await on_auto_connect_enabled(context)
    return {}
