"""Client requests that change the server-wide settings."""

from dataclasses import replace

from ..models.application_context import ApplicationContext
from ..models.outbound_test import OutboundTest, OutboundTestRule
from ..models.serialization import JsonValue
from ..request_error import ErrorCode, RequestError, expect_fields, field_value
from .core import connect_best_outbound_server
from .subscriptions import schedule_refresh_subscriptions

MODEL = "server_settings"


def _outbound_tests(payload: dict[str, JsonValue]) -> tuple[OutboundTest, ...]:
    """Parse [{url, alias, rule}, ...]; errors name the item, e.g. outbound_tests[1].rule."""
    items = payload["outbound_tests"]
    if not isinstance(items, list):
        raise RequestError(
            ErrorCode.BAD_REQUEST,
            "Field outbound_tests must be list",
            {"field": "outbound_tests"},
        )
    tests = []
    for index, item in enumerate(items):
        prefix = f"outbound_tests[{index}]"
        if not isinstance(item, dict):
            raise RequestError(
                ErrorCode.BAD_REQUEST, f"Field {prefix} must be object", {"field": prefix}
            )
        expect_fields(item, {"url", "alias", "rule"}, prefix=f"{prefix}.")
        url, alias, rule = (
            field_value(item, name, str, prefix=f"{prefix}.") for name in ("url", "alias", "rule")
        )
        try:
            rule = OutboundTestRule(rule)
        except ValueError:
            raise RequestError(
                ErrorCode.VALIDATION_ERROR,
                f"Unknown outbound test rule {rule}",
                {"field": f"{prefix}.rule"},
            ) from None
        try:
            tests.append(OutboundTest(url=url, alias=alias, rule=rule))
        except ValueError as error:
            raise RequestError(ErrorCode.VALIDATION_ERROR, str(error), {"field": prefix}) from None
    return tuple(tests)


async def change_server_settings(
    context: ApplicationContext, payload: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """payload: {id: 0, subscription_refresh_interval?, outbound_tests?, auto_connect?}.

    outbound_tests replaces the whole list. A new interval restarts the refresh
    timer, counting from now. auto_connect true connects the best server before
    the response (connect_best_outbound_server). last_subscription_refresh is
    maintained by the server and cannot be changed.
    """
    expect_fields(
        payload, {"id"}, {"subscription_refresh_interval", "outbound_tests", "auto_connect"}
    )
    if field_value(payload, "id", int) != 0:
        raise RequestError(ErrorCode.NOT_FOUND, "Server settings have id 0", {"field": "id"})
    settings = context.settings.server_settings.get()
    changes = {}
    if "subscription_refresh_interval" in payload:
        changes["subscription_refresh_interval"] = field_value(
            payload, "subscription_refresh_interval", int
        )
    if "outbound_tests" in payload:
        changes["outbound_tests"] = _outbound_tests(payload)
    if "auto_connect" in payload:
        changes["auto_connect"] = field_value(payload, "auto_connect", bool)
    interval = settings.subscription_refresh_interval
    settings = replace(settings, **changes)
    context.settings.server_settings.save(settings)
    await context.sync.notify(MODEL)
    if settings.subscription_refresh_interval != interval:
        schedule_refresh_subscriptions(context)
    if changes.get("auto_connect"):
        await connect_best_outbound_server(context)
    return {}
