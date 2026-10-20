"""Tests for .github/scripts/sync_telemetry_error_issues.py."""

from __future__ import annotations

import functools
import importlib.util
import json
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

if TYPE_CHECKING:
    from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / ".github" / "scripts" / "sync_telemetry_error_issues.py"
EASTERN = ZoneInfo("America/New_York")


@functools.cache
def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sync_telemetry_error_issues", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve their annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_script() -> ModuleType:
    return _load_script()


# Reporting window and command-line interface


@pytest.mark.parametrize(
    "run_time",
    [
        datetime(2026, 10, 21, 0, 45, tzinfo=EASTERN),
        datetime(2026, 10, 21, 3, 30, tzinfo=EASTERN),
        datetime(2026, 10, 21, 4, 45, tzinfo=UTC),
    ],
)
def test_window_scheduled_run_reports_the_previous_eastern_day(
    sync_script: ModuleType, run_time: datetime
) -> None:
    window = sync_script.reporting_window(sync_script.default_report_date(run_time))

    assert window.start == datetime(2026, 10, 20, 0, 0, tzinfo=EASTERN)
    assert window.end == datetime(2026, 10, 21, 0, 0, tzinfo=EASTERN)
    assert window.hours == 24


def test_window_default_date_follows_eastern_time_not_utc(
    sync_script: ModuleType,
) -> None:
    # 02:00 UTC on 21 October is still 22:00 on 20 October in New York.
    run_time = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)

    assert sync_script.default_report_date(run_time) == date(2026, 10, 19)


def test_window_spring_forward_day_lasts_23_hours(sync_script: ModuleType) -> None:
    window = sync_script.reporting_window(date(2026, 3, 8))

    assert window.start.utcoffset() == timedelta(hours=-5)
    assert window.end.utcoffset() == timedelta(hours=-4)
    assert window.hours == 23


def test_window_fall_back_day_lasts_25_hours(sync_script: ModuleType) -> None:
    window = sync_script.reporting_window(date(2026, 11, 1))

    assert window.start.utcoffset() == timedelta(hours=-4)
    assert window.end.utcoffset() == timedelta(hours=-5)
    assert window.hours == 25


def test_window_bounds_convert_to_utc_for_queries(sync_script: ModuleType) -> None:
    window = sync_script.reporting_window(date(2026, 11, 1))

    assert window.start.astimezone(UTC) == datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
    assert window.end.astimezone(UTC) == datetime(2026, 11, 2, 5, 0, tzinfo=UTC)


def test_cli_parses_project_dry_run_and_report_date(sync_script: ModuleType) -> None:
    arguments = sync_script.parse_arguments(
        [
            "--project-id",
            "policyengine-observability",
            "--dry-run",
            "--report-date",
            "2026-10-19",
        ]
    )

    assert arguments.project_id == "policyengine-observability"
    assert arguments.dry_run is True
    assert arguments.report_date == date(2026, 10, 19)


def test_cli_defaults_to_a_live_run_of_the_previous_day(
    sync_script: ModuleType,
) -> None:
    arguments = sync_script.parse_arguments(
        ["--project-id", "policyengine-observability"]
    )

    assert arguments.dry_run is False
    assert arguments.report_date is None


def test_cli_treats_an_empty_report_date_as_unset(sync_script: ModuleType) -> None:
    arguments = sync_script.parse_arguments(
        ["--project-id", "policyengine-observability", "--report-date", ""]
    )

    assert arguments.report_date is None


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--dry-run"],
        ["--project-id", "policyengine-observability", "--report-date", "20 Oct"],
    ],
)
def test_cli_rejects_missing_project_or_invalid_date_with_exit_code_2(
    sync_script: ModuleType, argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        sync_script.main(argv)

    assert raised.value.code == 2


# Normalization, stack frames and public value validation

STANDARD_STACK = """\
Traceback (most recent call last):
  File "/venv/lib/python3.12/site-packages/flask/app.py", line 880, in dispatch_request
    rv = self.dispatch_request()
         ^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/policyengine_api/routes/report_routes.py", line 41, in create_report
    return service.create(payload)
  File "/app/policyengine_api/services/report_service.py", line 88, in create
    session.flush()
  File "/venv/lib/python3.12/site-packages/sqlalchemy/orm/session.py", line 43, in flush
    self._flush(objects)
sqlalchemy.orm.exc.StaleDataError: SENTINEL message about 'reports'
"""

CHAINED_STACK = """\
Traceback (most recent call last):
  File "/app/policyengine_api/services/cache.py", line 12, in read
    return store[key]
KeyError: 'SENTINEL key'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/app/policyengine_api/routes/policy_routes.py", line 30, in get_policy
    return service.get(policy_id)
  File "/app/policyengine_api/services/policy_service.py", line 55, in get
    raise LookupError(policy_id)
LookupError: SENTINEL policy
"""

EXCEPTION_GROUP_STACK = """\
  + Exception Group Traceback (most recent call last):
  |   File "/root/policyengine_simulation_gateway/app.py", line 10, in run
  |     raise ExceptionGroup("SENTINEL group", errors)
  | ExceptionGroup: SENTINEL group (1 sub-exception)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "/root/policyengine_simulation_gateway/worker.py", line 22, in step
    |     raise ValueError("SENTINEL value")
    | ValueError: SENTINEL value
    +------------------------------------
"""


def _extract_frames(sync_script: ModuleType, stack: str) -> list[str]:
    """Apply the pattern the way BigQuery's REGEXP_EXTRACT_ALL does."""
    return re.findall(sync_script.FRAME_PATTERN, stack)


@pytest.mark.parametrize(
    ("service_name", "family"),
    [
        ("policyengine-simulation-py1-2-3", "policyengine-simulation-py"),
        ("policyengine-simulation-py0-412-16", "policyengine-simulation-py"),
        ("policyengine-api", "policyengine-api"),
        ("policyengine-simulation-gateway", "policyengine-simulation-gateway"),
        ("policyengine-stage12-us-worker", "policyengine-stage12-us-worker"),
    ],
)
def test_normalize_service_family_merges_simulation_versions(
    sync_script: ModuleType, service_name: str, family: str
) -> None:
    assert sync_script.service_family(service_name) == family


@pytest.mark.parametrize(
    ("environment_name", "environment_class"),
    [
        ("production", "production"),
        ("main", "production"),
        ("staging", "staging"),
        ("local", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_normalize_environment_maps_modal_main_to_production(
    sync_script: ModuleType, environment_name: str | None, environment_class: str
) -> None:
    assert sync_script.environment_class(environment_name) == environment_class


def test_frames_pattern_has_one_capturing_group_for_bigquery(
    sync_script: ModuleType,
) -> None:
    assert re.compile(sync_script.FRAME_PATTERN).groups == 1


def test_frames_pattern_extracts_frame_headers_without_source_or_message(
    sync_script: ModuleType,
) -> None:
    frames = _extract_frames(sync_script, STANDARD_STACK)

    assert [sync_script.frame_key(frame) for frame in frames] == [
        "flask/app.py:dispatch_request",
        "policyengine_api/routes/report_routes.py:create_report",
        "policyengine_api/services/report_service.py:create",
        "sqlalchemy/orm/session.py:flush",
    ]
    assert not any("SENTINEL" in frame or "\n" in frame for frame in frames)


def test_frames_pattern_reads_every_block_of_a_chained_traceback(
    sync_script: ModuleType,
) -> None:
    frames = _extract_frames(sync_script, CHAINED_STACK)

    assert [sync_script.frame_key(frame) for frame in frames] == [
        "policyengine_api/services/cache.py:read",
        "policyengine_api/routes/policy_routes.py:get_policy",
        "policyengine_api/services/policy_service.py:get",
    ]


def test_frames_pattern_reads_exception_group_tracebacks(
    sync_script: ModuleType,
) -> None:
    frames = _extract_frames(sync_script, EXCEPTION_GROUP_STACK)

    assert [sync_script.frame_key(frame) for frame in frames] == [
        "policyengine_simulation_gateway/app.py:run",
        "policyengine_simulation_gateway/worker.py:step",
    ]


def test_frames_pattern_skips_a_frame_header_cut_off_by_truncation(
    sync_script: ModuleType,
) -> None:
    cut_at = STANDARD_STACK.index("create_report") + len("create_re")
    frames = _extract_frames(sync_script, STANDARD_STACK[:cut_at])

    assert [sync_script.frame_key(frame) for frame in frames] == [
        "flask/app.py:dispatch_request",
    ]


@pytest.mark.parametrize(
    ("path", "normalized"),
    [
        (
            "/opt/venv/lib/python3.12/site-packages/sqlalchemy/orm/session.py",
            "sqlalchemy/orm/session.py",
        ),
        ("/usr/lib/python3/dist-packages/yaml/loader.py", "yaml/loader.py"),
        ("/usr/local/lib/python3.13/asyncio/tasks.py", "asyncio/tasks.py"),
        ("/app/policyengine_api/services/x.py", "policyengine_api/services/x.py"),
        (
            "/home/runner/work/api/api/policyengine_api/services/x.py",
            "policyengine_api/services/x.py",
        ),
        (
            "/root/policyengine_simulation_gateway/app.py",
            "policyengine_simulation_gateway/app.py",
        ),
        ("/pkg/synchronicity/combined_types.py", "synchronicity/combined_types.py"),
        ("<frozen runpy>", "<frozen runpy>"),
    ],
)
def test_frames_paths_drop_installation_prefixes(
    sync_script: ModuleType, path: str, normalized: str
) -> None:
    assert sync_script.normalize_path(path) == normalized


def test_frames_keys_ignore_line_numbers(sync_script: ModuleType) -> None:
    first = sync_script.frame_key('/app/policyengine_api/x.py", line 10, in handler')
    second = sync_script.frame_key('/srv/policyengine_api/x.py", line 99, in handler')

    assert first == second == "policyengine_api/x.py:handler"


def test_frames_choose_the_three_innermost_application_frames(
    sync_script: ModuleType,
) -> None:
    frames = [
        '/app/policyengine_api/routes/a.py", line 1, in outer',
        '/app/policyengine_api/services/b.py", line 2, in middle',
        '/app/policyengine_api/services/c.py", line 3, in inner',
        '/opt/venv/lib/python3.12/site-packages/sqlalchemy/orm/d.py", line 4, in lib',
        '/app/policyengine_api/services/e.py", line 5, in callback',
        '/venv/lib/python3.12/site-packages/sqlalchemy/orm/f.py", line 6, in raises',
    ]

    assert sync_script.fingerprint_frames(frames) == (
        "policyengine_api/services/b.py:middle",
        "policyengine_api/services/c.py:inner",
        "policyengine_api/services/e.py:callback",
    )


def test_frames_count_simulation_and_stage12_packages_as_application_code(
    sync_script: ModuleType,
) -> None:
    frames = [
        '/pkg/modal/_runtime.py", line 1, in run',
        '/root/policyengine_simulation_executor/run.py", line 2, in execute',
        '/root/policyengine_stage12_persistence/store.py", line 3, in save',
        '/pkg/synchronicity/combined_types.py", line 4, in __call__',
    ]

    assert sync_script.fingerprint_frames(frames) == (
        "policyengine_simulation_executor/run.py:execute",
        "policyengine_stage12_persistence/store.py:save",
    )


def test_frames_without_application_frames_use_the_innermost_frames(
    sync_script: ModuleType,
) -> None:
    frames = [
        '/usr/local/lib/python3.13/asyncio/a.py", line 1, in first',
        '/pkg/modal/b.py", line 2, in second',
        '/pkg/modal/c.py", line 3, in third',
        '/pkg/synchronicity/d.py", line 4, in fourth',
    ]

    assert sync_script.fingerprint_frames(frames) == (
        "modal/b.py:second",
        "modal/c.py:third",
        "synchronicity/d.py:fourth",
    )


@pytest.mark.parametrize("frames", [[], None, ["not a frame header"]])
def test_frames_without_a_stack_use_a_placeholder(
    sync_script: ModuleType, frames: list[str] | None
) -> None:
    assert sync_script.fingerprint_frames(frames) == ("-",)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("StaleDataError", "StaleDataError"),
        ("sqlalchemy.orm.exc.StaleDataError", "sqlalchemy.orm.exc.StaleDataError"),
        ("SENTINEL message with spaces", "<unrecognized>"),
        ("Error: 'quoted'", "<unrecognized>"),
        ("E" * 200, "<unrecognized>"),
        (None, "-"),
        ("", "-"),
    ],
)
def test_public_error_type_allows_only_class_names(
    sync_script: ModuleType, value: str | None, expected: str
) -> None:
    assert sync_script.public_error_type(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>",
            "/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>",
        ),
        ("/v2/user-policies", "/v2/user-policies"),
        ("/jobs/{job_id}", "/jobs/{job_id}"),
        ("<unmatched>", "<unmatched>"),
        ("/us/policy/12345", "<unrecognized>"),
        ("/v2/households/3f2b1c9e-8d7a-4c1b-9e2f-0a1b2c3d4e5f", "<unrecognized>"),
        ("/us/report?token=SENTINEL", "<unrecognized>"),
        ("SENTINEL route", "<unrecognized>"),
        ("/" + "a" * 300, "<unrecognized>"),
        (None, "-"),
        ("", "-"),
    ],
)
def test_public_route_allows_only_route_templates(
    sync_script: ModuleType, value: str | None, expected: str
) -> None:
    assert sync_script.public_route(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("policyengine-api", "policyengine-api"),
        ("policyengine-simulation-py", "policyengine-simulation-py"),
        ("SENTINEL family", "<unrecognized>"),
        ("Policyengine_API", "<unrecognized>"),
        (None, "-"),
    ],
)
def test_public_family_allows_only_service_names(
    sync_script: ModuleType, value: str | None, expected: str
) -> None:
    assert sync_script.public_family(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("simulation.dispatch", "simulation.dispatch"),
        ("stage12/run_comparison", "stage12/run_comparison"),
        ("SENTINEL operation", "<unrecognized>"),
        (None, "-"),
    ],
)
def test_public_operation_allows_only_operation_names(
    sync_script: ModuleType, value: str | None, expected: str
) -> None:
    assert sync_script.public_operation(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (500, 500),
        ("503", 503),
        (99, None),
        (600, None),
        ("SENTINEL", None),
        (None, None),
    ],
)
def test_public_status_allows_only_http_status_codes(
    sync_script: ModuleType, value: object, expected: int | None
) -> None:
    assert sync_script.public_status(value) == expected


# Primary record per failure and fingerprints

FINGERPRINT_KEY = b"k" * 32
APPLICATION_FRAMES = (
    '/app/policyengine_api/routes/report_routes.py", line 41, in create_report',
    '/app/policyengine_api/services/report_service.py", line 88, in create',
    '/venv/lib/python3.12/site-packages/sqlalchemy/orm/session.py", line 43, in flush',
)


def _record(sync_script: ModuleType, **overrides: object) -> object:
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
    return sync_script.ErrorRecord(**fields)


def _exception_record(sync_script: ModuleType, **overrides: object) -> object:
    fields: dict[str, object] = {
        "event_name": "exception.recorded",
        "error_type": "StaleDataError",
        "error_handled": False,
        "frames": APPLICATION_FRAMES,
        "status_code": 500,
    }
    fields.update(overrides)
    return _record(sync_script, **fields)


def _message_record(sync_script: ModuleType, **overrides: object) -> object:
    fields: dict[str, object] = {"message_template": "failed to save"}
    fields.update(overrides)
    return _record(sync_script, **fields)


def _failed_request_record(sync_script: ModuleType, **overrides: object) -> object:
    fields: dict[str, object] = {"event_name": "request.completed", "status_code": 500}
    fields.update(overrides)
    return _record(sync_script, **fields)


def test_primary_prefers_the_exception_record_of_a_failed_request(
    sync_script: ModuleType,
) -> None:
    exception = _exception_record(sync_script)
    records = [
        _message_record(sync_script),
        exception,
        _failed_request_record(sync_script),
    ]

    assert sync_script.primary_records(records) == [exception]


def test_primary_falls_back_to_the_message_record(sync_script: ModuleType) -> None:
    message = _message_record(sync_script)

    primary = sync_script.primary_records(
        [_failed_request_record(sync_script), message]
    )

    assert primary == [message]
    assert primary[0].kind == "message"


def test_primary_falls_back_to_the_failed_request_record(
    sync_script: ModuleType,
) -> None:
    failed_request = _failed_request_record(sync_script)

    primary = sync_script.primary_records([failed_request])

    assert primary == [failed_request]
    assert primary[0].kind == "failed_request"


def test_primary_prefers_an_unhandled_exception_over_a_handled_one(
    sync_script: ModuleType,
) -> None:
    handled = _exception_record(sync_script, error_type="KeyError", error_handled=True)
    unhandled = _exception_record(
        sync_script,
        timestamp=datetime(2026, 10, 20, 16, 0, 1, tzinfo=UTC),
        error_type="LookupError",
    )

    assert sync_script.primary_records([handled, unhandled]) == [unhandled]


def test_primary_treats_a_request_completed_record_with_error_fields_as_an_exception(
    sync_script: ModuleType,
) -> None:
    completed = _failed_request_record(
        sync_script, error_type="StaleDataError", frames=APPLICATION_FRAMES
    )

    assert completed.kind == "exception"
    assert sync_script.primary_records([completed]) == [completed]


def test_primary_correlates_by_trace_when_the_request_id_is_missing(
    sync_script: ModuleType,
) -> None:
    exception = _exception_record(sync_script, request_key=None)
    message = _message_record(sync_script, request_key=None)

    assert sync_script.primary_records([message, exception]) == [exception]


def test_primary_records_without_request_or_trace_stand_alone(
    sync_script: ModuleType,
) -> None:
    first = _message_record(sync_script, request_key=None, trace_key=None)
    second = _message_record(
        sync_script,
        request_key=None,
        trace_key=None,
        timestamp=datetime(2026, 10, 20, 17, 0, tzinfo=UTC),
    )

    assert sync_script.primary_records([second, first]) == [first, second]


def test_primary_keeps_failures_of_different_services_separate(
    sync_script: ModuleType,
) -> None:
    api_failure = _failed_request_record(sync_script)
    simulation_failure = _exception_record(
        sync_script,
        service_name="policyengine-simulation-entry",
        frames=(),
    )

    primary = sync_script.primary_records([api_failure, simulation_failure])

    assert primary == [api_failure, simulation_failure]


def test_fingerprint_exception_ignores_lines_path_prefixes_and_routes(
    sync_script: ModuleType,
) -> None:
    moved_frames = tuple(
        frame.replace("/app/", "/srv/checkout/").replace("line 4", "line 9")
        for frame in APPLICATION_FRAMES
    )
    first = _exception_record(sync_script)
    second = _exception_record(
        sync_script,
        frames=moved_frames,
        route="/<country_id>/economy/<int:policy_id>/over/<int:baseline_policy_id>",
    )

    assert sync_script.fingerprint(first, FINGERPRINT_KEY) == sync_script.fingerprint(
        second, FINGERPRINT_KEY
    )


def test_fingerprint_exception_merges_simulation_service_versions(
    sync_script: ModuleType,
) -> None:
    first = _exception_record(
        sync_script, service_name="policyengine-simulation-py1-2-3"
    )
    second = _exception_record(
        sync_script, service_name="policyengine-simulation-py1-2-4"
    )

    assert sync_script.fingerprint(first, FINGERPRINT_KEY) == sync_script.fingerprint(
        second, FINGERPRINT_KEY
    )


@pytest.mark.parametrize(
    "change",
    [
        {"error_type": "ValueError"},
        {"frames": APPLICATION_FRAMES[:1]},
        {"service_name": "policyengine-simulation-entry"},
    ],
)
def test_fingerprint_exception_differs_by_type_frames_and_service(
    sync_script: ModuleType, change: dict[str, object]
) -> None:
    original = _exception_record(sync_script)
    changed = _exception_record(sync_script, **change)

    assert sync_script.fingerprint(
        original, FINGERPRINT_KEY
    ) != sync_script.fingerprint(changed, FINGERPRINT_KEY)


def test_fingerprint_depends_on_the_key(sync_script: ModuleType) -> None:
    record = _exception_record(sync_script)

    assert sync_script.fingerprint(record, FINGERPRINT_KEY) != sync_script.fingerprint(
        record, b"j" * 32
    )


def test_fingerprint_is_16_hex_characters(sync_script: ModuleType) -> None:
    value = sync_script.fingerprint(_exception_record(sync_script), FINGERPRINT_KEY)

    assert re.fullmatch(r"[0-9a-f]{16}", value)


def test_fingerprint_key_parts_for_each_kind(sync_script: ModuleType) -> None:
    exception = _exception_record(sync_script)
    message = _message_record(
        sync_script,
        attribute_error_type="TimeoutError",
        failure_category="upstream",
    )
    operation_message = _message_record(
        sync_script, route=None, operation_name="simulation.dispatch"
    )
    failed_request = _failed_request_record(sync_script, status_code=502)

    assert sync_script.fingerprint_parts(exception) == (
        "exception",
        "policyengine-api",
        "StaleDataError",
        "policyengine_api/routes/report_routes.py:create_report",
        "policyengine_api/services/report_service.py:create",
    )
    assert sync_script.fingerprint_parts(message) == (
        "message",
        "policyengine-api",
        "/<country_id>/report",
        "failed to save",
        "TimeoutError",
        "upstream",
    )
    assert sync_script.fingerprint_parts(operation_message)[2] == "simulation.dispatch"
    assert sync_script.fingerprint_parts(failed_request) == (
        "failed_request",
        "policyengine-api",
        "/<country_id>/report",
        "502",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"message_template": "failed to load"},
        {"route": "/<country_id>/calculate"},
        {"attribute_error_type": "ValueError"},
        {"failure_category": "validation"},
    ],
)
def test_fingerprint_message_differs_by_each_key_part(
    sync_script: ModuleType, change: dict[str, object]
) -> None:
    original = _message_record(sync_script)
    changed = _message_record(sync_script, **change)

    assert sync_script.fingerprint(
        original, FINGERPRINT_KEY
    ) != sync_script.fingerprint(changed, FINGERPRINT_KEY)


def test_fingerprint_failed_request_differs_by_status(sync_script: ModuleType) -> None:
    first = _failed_request_record(sync_script, status_code=500)
    second = _failed_request_record(sync_script, status_code=504)

    assert sync_script.fingerprint(first, FINGERPRINT_KEY) != sync_script.fingerprint(
        second, FINGERPRINT_KEY
    )


@pytest.mark.parametrize("value", ["", "too-short", "x" * 31])
def test_fingerprint_key_rejects_a_secret_shorter_than_32_characters(
    sync_script: ModuleType, value: str
) -> None:
    with pytest.raises(ValueError, match="at least 32 characters"):
        sync_script.fingerprint_key(value)


def test_fingerprint_key_accepts_a_64_character_hex_secret(
    sync_script: ModuleType,
) -> None:
    assert sync_script.fingerprint_key("ab" * 32) == ("ab" * 32).encode()


# Measures per group

REPORT_DATE = date(2026, 10, 20)
# Noon Eastern on the report date: 12 hours after the window starts, and 180
# hours after the seven days before it start.
WINDOW_NOON = datetime(2026, 10, 20, 16, 0, tzinfo=UTC)


def _at(hours_after_window_noon: float) -> datetime:
    return WINDOW_NOON + timedelta(hours=hours_after_window_noon)


def _request_count(
    sync_script: ModuleType,
    route: str,
    requests: int,
    *,
    service_name: str = "policyengine-api",
    environment_name: str = "production",
) -> object:
    return sync_script.RequestCount(service_name, environment_name, route, requests)


def _only_group(sync_script: ModuleType, records: list, request_counts=()) -> object:
    groups = sync_script.build_groups(
        records,
        list(request_counts),
        sync_script.reporting_window(REPORT_DATE),
        FINGERPRINT_KEY,
    )
    assert len(groups) == 1
    return groups[0]


def test_measures_count_occurrences_requests_and_observability_ids(
    sync_script: ModuleType,
) -> None:
    records = [
        _exception_record(sync_script, request_key="r1", observability_key="o1"),
        _exception_record(
            sync_script, request_key="r2", observability_key="o1", timestamp=_at(1)
        ),
        _exception_record(
            sync_script, request_key="r3", observability_key="o2", timestamp=_at(2)
        ),
        _exception_record(
            sync_script, request_key="s1", environment_name="staging", timestamp=_at(3)
        ),
    ]

    group = _only_group(sync_script, records)

    assert group.production.occurrences == 3
    assert group.production.affected_requests == 3
    assert group.production.observability_ids == 2
    assert group.staging.occurrences == 1
    assert group.staging.affected_requests == 1
    assert group.staging.observability_ids == 0


def test_measures_affected_requests_fall_back_to_observability_id_then_trace(
    sync_script: ModuleType,
) -> None:
    records = [
        _exception_record(
            sync_script, request_key=None, trace_key=None, observability_key="o1"
        ),
        _exception_record(
            sync_script,
            request_key=None,
            trace_key=None,
            observability_key="o1",
            timestamp=_at(1),
        ),
        _exception_record(sync_script, request_key=None, trace_key="t1"),
        _exception_record(sync_script, request_key=None, trace_key=None),
        _exception_record(
            sync_script, request_key=None, trace_key=None, timestamp=_at(2)
        ),
    ]

    group = _only_group(sync_script, records)

    assert group.production.occurrences == 5
    # o1 once, t1 once, and each record without any identifier on its own.
    assert group.production.affected_requests == 4


def test_measures_error_rate_uses_requests_to_the_affected_routes(
    sync_script: ModuleType,
) -> None:
    records = [
        _exception_record(sync_script, request_key="r1", route="/<country_id>/report"),
        _exception_record(
            sync_script,
            request_key="r2",
            route="/<country_id>/calculate",
            timestamp=_at(1),
        ),
        _exception_record(
            sync_script,
            request_key="r3",
            route="/<country_id>/calculate",
            timestamp=_at(2),
        ),
    ]
    request_counts = [
        _request_count(sync_script, "/<country_id>/report", 200),
        _request_count(sync_script, "/<country_id>/calculate", 100),
        _request_count(sync_script, "/<country_id>/metadata", 5000),
        _request_count(
            sync_script, "/<country_id>/report", 10, environment_name="staging"
        ),
        _request_count(
            sync_script,
            "/<country_id>/report",
            7000,
            service_name="policyengine-simulation-entry",
        ),
    ]

    group = _only_group(sync_script, records, request_counts)

    assert group.production.route_requests == 300
    assert group.production.error_rate == pytest.approx(0.01)
    assert group.staging.error_rate is None


def test_measures_error_rate_counts_every_simulation_service_version(
    sync_script: ModuleType,
) -> None:
    records = [
        _failed_request_record(
            sync_script,
            service_name="policyengine-simulation-py1-2-3",
            route="/jobs/{job_id}",
        )
    ]
    request_counts = [
        _request_count(
            sync_script,
            "/jobs/{job_id}",
            30,
            service_name="policyengine-simulation-py1-2-3",
        ),
        _request_count(
            sync_script,
            "/jobs/{job_id}",
            70,
            service_name="policyengine-simulation-py1-2-4",
        ),
    ]

    group = _only_group(sync_script, records, request_counts)

    assert group.production.route_requests == 100
    assert group.production.error_rate == pytest.approx(0.01)


def test_measures_error_rate_is_unknown_without_route_requests(
    sync_script: ModuleType,
) -> None:
    group = _only_group(
        sync_script, [_message_record(sync_script, route=None, operation_name="sync")]
    )

    assert group.production.route_requests == 0
    assert group.production.error_rate is None


def test_measures_hourly_rates_for_the_window_and_the_previous_seven_days(
    sync_script: ModuleType,
) -> None:
    window_records = [
        _message_record(sync_script, request_key=f"w{index}", timestamp=_at(index))
        for index in range(6)
    ]
    previous_records = [
        _message_record(
            sync_script, request_key=f"p{index}", timestamp=_at(-13 - 4 * index)
        )
        for index in range(42)
    ]

    group = _only_group(sync_script, window_records + previous_records)

    assert group.production.occurrences == 6
    assert group.production.hourly_rate == pytest.approx(6 / 24)
    assert group.production.previous_hourly_rate == pytest.approx(42 / 168)


def test_measures_hourly_rate_uses_the_25_hour_fall_back_day(
    sync_script: ModuleType,
) -> None:
    fall_back_noon = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)
    records = [
        _message_record(
            sync_script,
            request_key=f"w{index}",
            timestamp=fall_back_noon + timedelta(hours=index),
        )
        for index in range(5)
    ]

    groups = sync_script.build_groups(
        records, [], sync_script.reporting_window(date(2026, 11, 1)), FINGERPRINT_KEY
    )

    assert groups[0].production.hourly_rate == pytest.approx(5 / 25)


def test_measures_first_and_last_seen_cover_the_queried_eight_days(
    sync_script: ModuleType,
) -> None:
    records = [
        _message_record(sync_script, request_key="early", timestamp=_at(-24 * 6)),
        _message_record(sync_script, request_key="latest", timestamp=_at(5)),
        _message_record(sync_script, request_key="middle", timestamp=_at(1)),
    ]

    group = _only_group(sync_script, records)

    assert group.production.first_seen == _at(-24 * 6)
    assert group.production.last_seen == _at(5)
    assert group.staging.first_seen is None
    assert group.staging.last_seen is None


def test_measures_ignore_records_outside_the_queried_days(
    sync_script: ModuleType,
) -> None:
    records = [
        _message_record(sync_script, request_key="in-window"),
        _message_record(sync_script, request_key="too-old", timestamp=_at(-24 * 9)),
        _message_record(sync_script, request_key="too-new", timestamp=_at(24)),
    ]

    group = _only_group(sync_script, records)

    assert group.production.occurrences == 1
    assert group.production.first_seen == WINDOW_NOON


def test_measures_report_only_groups_seen_in_the_window(
    sync_script: ModuleType,
) -> None:
    records = [
        _message_record(sync_script, request_key="today"),
        _message_record(
            sync_script,
            request_key="last-week",
            message_template="something else",
            timestamp=_at(-48),
        ),
    ]

    groups = sync_script.build_groups(
        records, [], sync_script.reporting_window(REPORT_DATE), FINGERPRINT_KEY
    )

    assert [group.fingerprint for group in groups] == [
        sync_script.fingerprint(records[0], FINGERPRINT_KEY)
    ]


def test_measures_ignore_environments_other_than_production_and_staging(
    sync_script: ModuleType,
) -> None:
    records = [
        _message_record(sync_script, environment_name="local"),
        _message_record(sync_script, environment_name=None, request_key="r2"),
    ]

    groups = sync_script.build_groups(
        records, [], sync_script.reporting_window(REPORT_DATE), FINGERPRINT_KEY
    )

    assert groups == []


def test_measures_describe_the_group_with_its_most_frequent_production_route(
    sync_script: ModuleType,
) -> None:
    records = [
        _exception_record(sync_script, request_key="r1", route="/<country_id>/report"),
        _exception_record(
            sync_script, request_key="r2", route="/<country_id>/calculate"
        ),
        _exception_record(
            sync_script, request_key="r3", route="/<country_id>/calculate"
        ),
        _exception_record(
            sync_script,
            request_key="s1",
            route="/<country_id>/report",
            environment_name="staging",
        ),
        _exception_record(
            sync_script,
            request_key="s2",
            route="/<country_id>/report",
            environment_name="staging",
        ),
    ]

    group = _only_group(sync_script, records)

    assert group.kind == "exception"
    assert group.family == "policyengine-api"
    assert group.error_type == "StaleDataError"
    assert group.route == "/<country_id>/calculate"


def test_measures_describe_groups_only_with_validated_values(
    sync_script: ModuleType,
) -> None:
    group = _only_group(
        sync_script,
        [
            _exception_record(
                sync_script,
                error_type="SENTINEL not a class",
                route="/us/policy/12345",
            )
        ],
    )

    assert group.error_type == "<unrecognized>"
    assert group.route == "<unrecognized>"


def test_measures_list_up_to_three_related_fingerprints_by_shared_traces(
    sync_script: ModuleType,
) -> None:
    base = _exception_record(sync_script, request_key="r1", trace_key="t1")
    base_second = _exception_record(
        sync_script, request_key="r2", trace_key="t2", timestamp=_at(1)
    )
    related_twice = [
        _message_record(
            sync_script,
            service_name="policyengine-simulation-entry",
            request_key=f"x{index}",
            trace_key=trace,
        )
        for index, trace in enumerate(("t1", "t2"))
    ]
    related_once = [
        _message_record(
            sync_script,
            service_name="policyengine-simulation-gateway",
            request_key=f"y{index}",
            trace_key="t1",
            message_template=template,
        )
        for index, template in enumerate(("first error", "second error", "third"))
    ]

    groups = sync_script.build_groups(
        [base, base_second, *related_twice, *related_once],
        [],
        sync_script.reporting_window(REPORT_DATE),
        FINGERPRINT_KEY,
    )
    by_fingerprint = {group.fingerprint: group for group in groups}
    base_group = by_fingerprint[sync_script.fingerprint(base, FINGERPRINT_KEY)]
    twice = sync_script.fingerprint(related_twice[0], FINGERPRINT_KEY)
    once = sorted(
        sync_script.fingerprint(record, FINGERPRINT_KEY) for record in related_once
    )

    assert base_group.related_fingerprints == (twice, once[0], once[1])


def test_measures_sort_groups_by_production_occurrences(
    sync_script: ModuleType,
) -> None:
    frequent = [
        _message_record(sync_script, request_key=f"f{index}", message_template="often")
        for index in range(3)
    ]
    staging_only = [
        _message_record(
            sync_script,
            request_key=f"s{index}",
            message_template="staging",
            environment_name="staging",
        )
        for index in range(5)
    ]
    rare = [_message_record(sync_script, request_key="rare", message_template="rare")]

    groups = sync_script.build_groups(
        staging_only + rare + frequent,
        [],
        sync_script.reporting_window(REPORT_DATE),
        FINGERPRINT_KEY,
    )

    assert [group.production.occurrences for group in groups] == [3, 1, 0]


def test_measures_count_production_occurrences_since_a_moment(
    sync_script: ModuleType,
) -> None:
    records = [
        _exception_record(sync_script, request_key="before", timestamp=_at(-30)),
        _exception_record(sync_script, request_key="r1", timestamp=_at(1)),
        _exception_record(sync_script, request_key="r2", timestamp=_at(2)),
        _exception_record(
            sync_script, request_key="r2", trace_key="t9", timestamp=_at(3)
        ),
        _exception_record(
            sync_script, request_key="staging", environment_name="staging"
        ),
    ]

    group = _only_group(sync_script, records)

    assert group.production_since(_at(-1)) == (2, 2)
    assert group.production_since(_at(-48)) == (3, 3)


# BigQuery queries and client

ACCESS_TOKEN = "fake-access-token"


class FakeTransport:
    """Records each HTTP request and answers with queued responses."""

    def __init__(self, sync_script: ModuleType, responses: list[object]) -> None:
        self.sync_script = sync_script
        self.responses = list(responses)
        self.requests: list[object] = []

    def __call__(self, request: object) -> object:
        self.requests.append(request)
        return self.responses.pop(0)

    def json_body(self, index: int) -> dict:
        return json.loads(self.requests[index].body)


def _json_response(
    sync_script: ModuleType, payload: object, status: int = 200, reason: str = "OK"
) -> object:
    return sync_script.HttpResponse(
        status=status, reason=reason, headers={}, body=json.dumps(payload).encode()
    )


def _cell(value: object) -> dict:
    if isinstance(value, list):
        return {"v": [{"v": item} for item in value]}
    return {"v": value}


def _query_response(
    fields: list[dict],
    rows: list[list[object]],
    *,
    page_token: str | None = None,
    job_complete: bool = True,
) -> dict:
    response: dict[str, object] = {
        "jobComplete": job_complete,
        "jobReference": {
            "projectId": "policyengine-observability",
            "jobId": "job-1",
            "location": "US",
        },
    }
    if job_complete:
        response["schema"] = {"fields": fields}
        response["rows"] = [{"f": [_cell(value) for value in row]} for row in rows]
    if page_token:
        response["pageToken"] = page_token
    return response


STRING_FIELD = {"name": "name", "type": "STRING", "mode": "NULLABLE"}


def _client(sync_script: ModuleType, transport: FakeTransport) -> object:
    return sync_script.BigQueryClient(
        "policyengine-observability", ACCESS_TOKEN, transport
    )


def _sent_parameters(transport: FakeTransport, index: int = 0) -> dict:
    return {
        parameter["name"]: parameter
        for parameter in transport.json_body(index)["queryParameters"]
    }


def test_bigquery_error_query_request_limits_cost_and_names_its_parameters(
    sync_script: ModuleType,
) -> None:
    transport = FakeTransport(
        sync_script, [_json_response(sync_script, _query_response([], []))]
    )
    window = sync_script.reporting_window(REPORT_DATE)

    sync_script.fetch_error_records(_client(sync_script, transport), window)

    request = transport.requests[0]
    body = transport.json_body(0)
    parameters = _sent_parameters(transport)
    assert request.method == "POST"
    assert request.url == (
        "https://bigquery.googleapis.com/bigquery/v2/projects/"
        "policyengine-observability/queries"
    )
    assert request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert body["useLegacySql"] is False
    assert body["parameterMode"] == "NAMED"
    assert body["maximumBytesBilled"] == str(5 * 1024**3)
    assert body["labels"] == {
        "purpose": "telemetry-error-issues",
        "query": "error-records",
    }
    assert body["defaultDataset"] == {
        "projectId": "policyengine-observability",
        "datasetId": "observability_logs",
    }
    assert body["formatOptions"] == {"useInt64Timestamp": True}
    assert parameters["query_start"]["parameterType"] == {"type": "TIMESTAMP"}
    assert parameters["query_start"]["parameterValue"]["value"] == (
        "2026-10-13 04:00:00+00:00"
    )
    assert parameters["window_end"]["parameterValue"]["value"] == (
        "2026-10-21 04:00:00+00:00"
    )
    assert parameters["frame_pattern"]["parameterValue"]["value"] == (
        sync_script.FRAME_PATTERN
    )
    assert [
        item["value"]
        for item in parameters["excluded_routes"]["parameterValue"]["arrayValues"]
    ] == ["/health", "/simulation-gateway-check", "/liveness-check", "/readiness-check"]


def test_bigquery_error_query_filters_application_error_records(
    sync_script: ModuleType,
) -> None:
    sql = sync_script.ERROR_RECORDS_QUERY

    assert "FROM `_AllLogs`" in sql
    assert "timestamp >= @query_start AND timestamp < @window_end" in sql
    assert (
        "JSON_VALUE(json_payload, '$.schema_version') = "
        "'policyengine.observability.v2'" in sql
    )
    assert (
        "JSON_VALUE(json_payload, '$.\"service.namespace\"') = "
        "'policyengine.api-v1'" in sql
    )
    assert "severity_number >= 500" in sql
    assert "NOT IN UNNEST(@excluded_routes)" in sql
    assert "QUALIFY ROW_NUMBER() OVER" in sql


def test_bigquery_error_query_reads_stacks_and_messages_only_through_expressions(
    sync_script: ModuleType,
) -> None:
    sql = sync_script.ERROR_RECORDS_QUERY
    stack = "JSON_VALUE(json_payload, '$.\"error.stack\"')"

    assert sql.count("error.stack") == 2
    assert f"REGEXP_EXTRACT_ALL({stack}, @frame_pattern)" in sql
    assert f"LENGTH({stack}) >= 16384" in sql
    assert sql.count("$.message") == 1
    assert "REGEXP_REPLACE(JSON_VALUE(json_payload, '$.message')" in sql
    assert "error.message" not in sql
    assert "SELECT *" not in sql
    assert "json_payload AS" not in sql


@pytest.mark.parametrize(
    "identifier",
    [
        "JSON_VALUE(json_payload, '$.\"request.id\"')",
        "JSON_VALUE(json_payload, '$.attributes.observability_id')",
    ],
)
def test_bigquery_error_query_hashes_identifiers(
    sync_script: ModuleType, identifier: str
) -> None:
    sql = sync_script.ERROR_RECORDS_QUERY

    assert sql.count(identifier) == 1
    assert f"TO_HEX(SHA256({identifier}))" in sql


def test_bigquery_error_query_hashes_the_trace(sync_script: ModuleType) -> None:
    sql = sync_script.ERROR_RECORDS_QUERY

    assert "TO_HEX(SHA256(COALESCE(" in sql
    assert sql.count("$.trace_id") == 1


def test_bigquery_request_count_query_counts_completed_requests_in_the_window(
    sync_script: ModuleType,
) -> None:
    sql = sync_script.REQUEST_COUNTS_QUERY
    transport = FakeTransport(
        sync_script, [_json_response(sync_script, _query_response([], []))]
    )

    sync_script.fetch_request_counts(
        _client(sync_script, transport), sync_script.reporting_window(REPORT_DATE)
    )

    parameters = _sent_parameters(transport)
    assert "JSON_VALUE(json_payload, '$.\"event.name\"') = 'request.completed'" in sql
    assert "COUNT(*) AS requests" in sql
    assert "GROUP BY service_name, environment_name, route" in sql
    assert "timestamp >= @window_start AND timestamp < @window_end" in sql
    assert parameters["window_start"]["parameterValue"]["value"] == (
        "2026-10-20 04:00:00+00:00"
    )
    assert transport.json_body(0)["labels"]["query"] == "request-counts"


def test_bigquery_client_polls_until_the_job_completes(sync_script: ModuleType) -> None:
    transport = FakeTransport(
        sync_script,
        [
            _json_response(sync_script, _query_response([], [], job_complete=False)),
            _json_response(sync_script, _query_response([], [], job_complete=False)),
            _json_response(sync_script, _query_response([STRING_FIELD], [["done"]])),
        ],
    )

    rows = _client(sync_script, transport).query("SELECT 1", [], "test")

    assert rows == [{"name": "done"}]
    poll = urlparse(transport.requests[1].url)
    assert transport.requests[1].method == "GET"
    assert poll.path.endswith("/projects/policyengine-observability/queries/job-1")
    assert parse_qs(poll.query)["location"] == ["US"]
    assert parse_qs(poll.query)["formatOptions.useInt64Timestamp"] == ["true"]


def test_bigquery_client_follows_page_tokens(sync_script: ModuleType) -> None:
    transport = FakeTransport(
        sync_script,
        [
            _json_response(
                sync_script,
                _query_response([STRING_FIELD], [["first"]], page_token="page-2"),
            ),
            _json_response(sync_script, _query_response([STRING_FIELD], [["second"]])),
        ],
    )

    rows = _client(sync_script, transport).query("SELECT 1", [], "test")

    assert rows == [{"name": "first"}, {"name": "second"}]
    page = parse_qs(urlparse(transport.requests[1].url).query)
    assert page["pageToken"] == ["page-2"]
    assert page["location"] == ["US"]


def test_bigquery_client_gives_up_on_a_job_that_never_completes(
    sync_script: ModuleType,
) -> None:
    pending = _json_response(sync_script, _query_response([], [], job_complete=False))
    transport = FakeTransport(sync_script, [pending] * 200)

    with pytest.raises(sync_script.BigQueryError, match="did not complete"):
        _client(sync_script, transport).query("SELECT 1", [], "test")


def test_bigquery_client_converts_row_values_from_strings(
    sync_script: ModuleType,
) -> None:
    fields = [
        {"name": "text", "type": "STRING", "mode": "NULLABLE"},
        {"name": "count", "type": "INTEGER", "mode": "NULLABLE"},
        {"name": "flag", "type": "BOOLEAN", "mode": "NULLABLE"},
        {"name": "moment", "type": "TIMESTAMP", "mode": "NULLABLE"},
        {"name": "items", "type": "STRING", "mode": "REPEATED"},
        {"name": "missing", "type": "INTEGER", "mode": "NULLABLE"},
    ]
    row = ["value", "42", "true", "1792512000000001", ["a", "b"], None]
    transport = FakeTransport(
        sync_script, [_json_response(sync_script, _query_response(fields, [row]))]
    )

    rows = _client(sync_script, transport).query("SELECT 1", [], "test")

    assert rows == [
        {
            "text": "value",
            "count": 42,
            "flag": True,
            "moment": datetime(2026, 10, 20, 16, 0, 0, 1, tzinfo=UTC),
            "items": ["a", "b"],
            "missing": None,
        }
    ]


def test_bigquery_http_error_reports_only_the_status_and_reason(
    sync_script: ModuleType,
) -> None:
    error_body = {
        "error": {
            "code": 400,
            "message": "SENTINEL value echoed from a row",
            "errors": [{"reason": "invalidQuery", "message": "SENTINEL detail"}],
        }
    }
    transport = FakeTransport(
        sync_script,
        [_json_response(sync_script, error_body, status=400, reason="Bad Request")],
    )

    with pytest.raises(sync_script.BigQueryError) as raised:
        _client(sync_script, transport).query("SELECT 1", [], "test")

    assert str(raised.value) == "BigQuery request failed: HTTP 400 invalidQuery"
    assert raised.value.status == 400
    assert raised.value.reason == "invalidQuery"


def test_bigquery_http_error_without_a_json_reason_uses_the_status_phrase(
    sync_script: ModuleType,
) -> None:
    response = sync_script.HttpResponse(
        status=503, reason="Service Unavailable", headers={}, body=b"SENTINEL <html>"
    )
    transport = FakeTransport(sync_script, [response])

    with pytest.raises(sync_script.BigQueryError) as raised:
        _client(sync_script, transport).query("SELECT 1", [], "test")

    assert str(raised.value) == "BigQuery request failed: HTTP 503 Service Unavailable"


def test_bigquery_rows_become_error_records(sync_script: ModuleType) -> None:
    row = {
        "timestamp": WINDOW_NOON,
        "service_name": "policyengine-api",
        "environment_name": "production",
        "event_name": "exception.recorded",
        "error_type": "StaleDataError",
        "error_handled": "false",
        "frames": list(APPLICATION_FRAMES),
        "stack_truncated": False,
        "message_template": "",
        "attribute_error_type": None,
        "failure_category": None,
        "route": "/<country_id>/report",
        "status_code": "500",
        "operation_name": None,
        "request_key": "aa",
        "observability_key": None,
        "trace_key": "bb",
    }

    record = sync_script.error_record_from_row(row)

    assert record == _exception_record(sync_script, request_key="aa", trace_key="bb")


def test_bigquery_rows_tolerate_missing_and_malformed_values(
    sync_script: ModuleType,
) -> None:
    row = {
        "timestamp": WINDOW_NOON,
        "service_name": None,
        "environment_name": None,
        "event_name": None,
        "error_type": None,
        "error_handled": "SENTINEL",
        "frames": None,
        "stack_truncated": None,
        "message_template": None,
        "attribute_error_type": None,
        "failure_category": None,
        "route": None,
        "status_code": "SENTINEL",
        "operation_name": None,
        "request_key": None,
        "observability_key": None,
        "trace_key": None,
    }

    record = sync_script.error_record_from_row(row)

    assert record.service_name == "-"
    assert record.error_handled is None
    assert record.frames == ()
    assert record.stack_truncated is False
    assert record.status_code is None


def test_bigquery_rows_become_request_counts(sync_script: ModuleType) -> None:
    rows = [
        {
            "service_name": "policyengine-api",
            "environment_name": "production",
            "route": "/<country_id>/report",
            "requests": 120,
        }
    ]
    transport = FakeTransport(
        sync_script,
        [
            _json_response(
                sync_script,
                _query_response(
                    [
                        {"name": "service_name", "type": "STRING"},
                        {"name": "environment_name", "type": "STRING"},
                        {"name": "route", "type": "STRING"},
                        {"name": "requests", "type": "INTEGER"},
                    ],
                    [list(map(str, rows[0].values()))],
                ),
            )
        ],
    )

    counts = sync_script.fetch_request_counts(
        _client(sync_script, transport), sync_script.reporting_window(REPORT_DATE)
    )

    assert counts == [
        _request_count(sync_script, "/<country_id>/report", 120),
    ]
