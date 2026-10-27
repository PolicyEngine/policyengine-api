"""Records, stacks, times and settings shared by several test modules."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from telemetry_error_issues.bigquery import CHAINED_EXCEPTION_PATTERN, FRAME_PATTERN
from telemetry_error_issues.groups import RequestCount
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


PROJECT_ID = "policyengine-observability"


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
