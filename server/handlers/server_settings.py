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
    expect_fields(
        payload,
        {"id"},
        {
            "subscription_refresh_interval",
            "auto_connect",
            "outbound_mode",
            "final_outbound_enabled",
            "final_outbound_uri",
        },
    )
    if field_value(payload, "id", int) != 0:
        raise RequestError(ErrorCode.NOT_FOUND, "Server settings have id 0", {"field": "id"})
    async with context.core_lock:
        previous = context.settings.server_settings.get()
        changes = {}
        for name, kind in (
            ("subscription_refresh_interval", int),
            ("auto_connect", bool),
            ("outbound_mode", str),
            ("final_outbound_enabled", bool),
            ("final_outbound_uri", str),
        ):
            if name in payload:
                changes[name] = (
                    None
                    if name == "final_outbound_uri" and payload[name] is None
                    else field_value(payload, name, bool)
                    if kind is bool
                    else field_value(payload, name, int)
                    if kind is int
                    else field_value(payload, name, str)
                )
        if changes.get("outbound_mode") == "server":
            changes.update(auto_connect=False, final_outbound_enabled=False)
        try:
            settings = replace(previous, **changes)
        except ValueError as error:
            raise RequestError(ErrorCode.VALIDATION_ERROR, str(error)) from None
        if settings.outbound_mode == "server" and settings.auto_connect:
            raise RequestError(
                ErrorCode.VALIDATION_ERROR, "Auto-connect is unavailable in server mode"
            )
        egress_changed = any(
            name in changes
            for name in ("outbound_mode", "final_outbound_uri", "final_outbound_enabled")
        )
        if egress_changed:
            try:
                await context.core_client.egress_set(settings)
            except Exception:  # noqa: BLE001 - never expose connection credentials
                raise RequestError(
                    ErrorCode.CORE_ERROR, "Could not apply outbound settings"
                ) from None
        context.settings.server_settings.save(settings)
    await context.sync.notify(MODEL)
    if settings.subscription_refresh_interval != previous.subscription_refresh_interval:
        schedule_refresh_subscriptions(context)
    if settings.auto_connect and not previous.auto_connect:
        await on_auto_connect_enabled(context)
    return {}
