"""Records, stacks, times and settings shared by several test modules."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from telemetry_error_issues.bigquery import CHAINED_EXCEPTION_PATTERN, FRAME_PATTERN
from telemetry_error_issues.groups import RequestCount
from telemetry_error_issues.log_source import LogSource
from telemetry_error_issues.records import ErrorRecord

EASTERN = ZoneInfo("America/New_York")


def extract_frames(stack: str) -> list[str]:
    """Extract frames as the query does: REGEXP_REPLACE, then REGEXP_EXTRACT_ALL."""
    first_traceback = re.sub(CHAINED_EXCEPTION_PATTERN, "", stack)
    return re.findall(FRAME_PATTERN, first_traceback)


def chained_stack(recursion_depth: int) -> str:
    """Return a chained traceback whose cause recursed ``recursion_depth`` times."""
    library_frame = (
        '  File "/venv/lib/python3.12/site-packages/policyengine_core/simulation.py", '
        "line 500, in calculate\n    return self._calculate(variable_name, period)\n"
    )
    cause = (
        "Traceback (most recent call last):\n"
        '  File "/app/policyengine_api/services/household.py", line 40, in calculate\n'
        "    simulation.calculate(name)\n"
        f"{library_frame * recursion_depth}"
        "ValueError: SENTINEL cause\n"
    )
    final = (
        "Traceback (most recent call last):\n"
        '  File "/app/policyengine_api/routes/household_routes.py", line 12, in get\n'
        "    return service.calculate()\n"
        '  File "/app/policyengine_api/services/household.py", line 44, in calculate\n'
        "    raise CalculationError(name) from error\n"
        "CalculationError: SENTINEL final\n"
    )
    separator = (
        "\nThe above exception was the direct cause of the following exception:\n\n"
    )
    return f"{cause}{separator}{final}"


FINGERPRINT_KEY = b"k" * 32
APPLICATION_FRAMES = (
    '/app/policyengine_api/routes/report_routes.py", line 41, in create_report',
    '/app/policyengine_api/services/report_service.py", line 88, in create',
    '/venv/lib/python3.12/site-packages/sqlalchemy/orm/session.py", line 43, in flush',
)


def _record(**overrides: object) -> object:
    fields: dict[str, object] = {
        "timestamp": datetime(2026, 10, 20, 16, 0, tzinfo=UTC),
        "service_name": "policyengine-api",
        "environment_name": "production",
        "event_name": None,
        "error_type": None,
        "error_handled": None,
        "frames": (),
        "stack_truncated": False,
        "message_template": None,
        "attribute_error_type": None,
        "failure_category": None,
        "route": "/<country_id>/report",
        "status_code": None,
        "operation_name": None,
        "request_key": "request-1",
        "observability_key": None,
        "trace_key": "trace-1",
    }
    fields.update(overrides)
    return ErrorRecord(**fields)


def exception_record(**overrides: object) -> object:
    fields: dict[str, object] = {
        "event_name": "exception.recorded",
        "error_type": "StaleDataError",
        "error_handled": False,
        "frames": APPLICATION_FRAMES,
        "status_code": 500,
    }
    fields.update(overrides)
    return _record(**fields)


def message_record(**overrides: object) -> object:
    fields: dict[str, object] = {"message_template": "failed to save"}
    fields.update(overrides)
    return _record(**fields)


def failed_request_record(**overrides: object) -> object:
    fields: dict[str, object] = {"event_name": "request.completed", "status_code": 500}
    fields.update(overrides)
    return _record(**fields)


REPORT_DATE = date(2026, 10, 20)
# Noon Eastern on the report date: 12 hours after the window starts, and 180
# hours after the seven days before it start.
WINDOW_NOON = datetime(2026, 10, 20, 16, 0, tzinfo=UTC)


def hours_after_window_noon(hours: float) -> datetime:
    return WINDOW_NOON + timedelta(hours=hours)


def request_count(
    route: str,
    requests: int,
    *,
    service_name: str = "policyengine-api",
    environment_name: str = "production",
) -> object:
    return RequestCount(service_name, environment_name, route, requests)


def input_orders(items: list) -> dict[str, list]:
    """Return ``items`` forward, reversed and in a fixed shuffled order.

    The shuffled order puts the items at odd positions first, then those at
    even positions from last to first, so it separates and reorders neighbours.
    """
    return {
        "forward": list(items),
        "reversed": items[::-1],
        "shuffled": [*items[1::2], *items[::2][::-1]],
    }


def failures_with_and_without_a_route() -> list:
    """Return one failed request on a route and two route-less failures."""
    return [
        exception_record(request_key="r1", route="/<country_id>/calculate"),
        exception_record(
            request_key=None,
            trace_key="t2",
            route=None,
            timestamp=hours_after_window_noon(1),
        ),
        exception_record(
            request_key=None,
            trace_key="t3",
            route=None,
            timestamp=hours_after_window_noon(2),
        ),
    ]


GATEWAY_SERVICE = "policyengine-simulation-gateway"


def failures_on_the_unmatched_route(failure_count: int = 15) -> list[ErrorRecord]:
    """Return gateway failures in separate requests that matched no route.

    The gateway logs ``<unmatched>`` as the route of such a request.
    """
    return [
        exception_record(
            service_name=GATEWAY_SERVICE,
            error_type="ValueError",
            route="<unmatched>",
            request_key=f"unmatched-{index}",
            timestamp=hours_after_window_noon(index / 10),
        )
        for index in range(failure_count)
    ]


PROJECT_ID = "policyengine-observability"
# The deployment's values of the repository variables that name the logs.
LOG_SOURCE = LogSource(
    project_id=PROJECT_ID,
    bucket="policyengine-observability",
    bucket_location="global",
    dataset="observability_logs",
    view="_AllLogs",
    service_namespace="policyengine.api-v1",
)
LOG_SOURCE_ENVIRONMENT = {
    "OBSERVABILITY_LOG_BUCKET": LOG_SOURCE.bucket,
    "OBSERVABILITY_LOG_BUCKET_LOCATION": LOG_SOURCE.bucket_location,
    "OBSERVABILITY_LOG_DATASET": LOG_SOURCE.dataset,
    "OBSERVABILITY_LOG_VIEW": LOG_SOURCE.view,
    "OBSERVABILITY_SERVICE_NAMESPACE": LOG_SOURCE.service_namespace,
}


def sentinel_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "timestamp": WINDOW_NOON,
        "service_name": "SENTINEL service name",
        "environment_name": "production",
        "event_name": "SENTINEL event",
        "error_type": "SENTINEL error type",
        "error_handled": "SENTINEL handled",
        "frames": [
            '/app/policyengine_api/SENTINEL.py", line 1, in SENTINEL_function',
            "SENTINEL frame text",
        ],
        "stack_truncated": "SENTINEL",
        "message_template": "SENTINEL message words",
        "attribute_error_type": "SENTINEL attribute type",
        "failure_category": "SENTINEL category",
        "route": "/SENTINEL/route?query=SENTINEL",
        "status_code": "SENTINEL",
        "operation_name": "SENTINEL operation",
        "request_key": "SENTINEL request",
        "observability_key": "SENTINEL observability",
        "trace_key": "SENTINEL trace",
    }
    row.update(overrides)
    return row
