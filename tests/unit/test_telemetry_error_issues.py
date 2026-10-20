"""Tests for .github/scripts/sync_telemetry_error_issues.py."""

from __future__ import annotations

import functools
import importlib.util
import io
import itertools
import json
import os
import re
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, quote, unquote, urlparse, urlsplit
from zoneinfo import ZoneInfo

import pytest
import yaml

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
    """Extract frames as the query does: REGEXP_REPLACE, then REGEXP_EXTRACT_ALL."""
    first_traceback = re.sub(sync_script.CHAINED_EXCEPTION_PATTERN, "", stack)
    return re.findall(sync_script.FRAME_PATTERN, first_traceback)


def _chained_stack(recursion_depth: int) -> str:
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


def test_frames_chained_traceback_contributes_only_its_first_traceback(
    sync_script: ModuleType,
) -> None:
    frames = _extract_frames(sync_script, CHAINED_STACK)

    assert [sync_script.frame_key(frame) for frame in frames] == [
        "policyengine_api/services/cache.py:read",
    ]


def test_frames_explicitly_chained_traceback_contributes_only_its_cause(
    sync_script: ModuleType,
) -> None:
    frames = _extract_frames(sync_script, _chained_stack(recursion_depth=2))

    assert [sync_script.frame_key(frame) for frame in frames] == [
        "policyengine_api/services/household.py:calculate",
        "policyengine_core/simulation.py:calculate",
        "policyengine_core/simulation.py:calculate",
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


def test_fingerprint_is_the_same_when_truncation_drops_the_final_traceback(
    sync_script: ModuleType,
) -> None:
    # The logging library keeps only the first 16,384 characters of a stack.
    short_stack = _chained_stack(recursion_depth=20)
    long_stack = _chained_stack(recursion_depth=120)[:16_384]
    assert "CalculationError" in short_stack
    assert "CalculationError" not in long_stack

    short = _exception_record(
        sync_script,
        error_type="CalculationError",
        frames=tuple(_extract_frames(sync_script, short_stack)),
    )
    long = _exception_record(
        sync_script,
        error_type="CalculationError",
        frames=tuple(_extract_frames(sync_script, long_stack)),
        stack_truncated=True,
    )

    assert sync_script.fingerprint(short, FINGERPRINT_KEY) == sync_script.fingerprint(
        long, FINGERPRINT_KEY
    )


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


def _failures_with_and_without_a_route(sync_script: ModuleType) -> list:
    """Return one failed request on a route and two route-less failures."""
    return [
        _exception_record(
            sync_script, request_key="r1", route="/<country_id>/calculate"
        ),
        _exception_record(
            sync_script, request_key=None, trace_key="t2", route=None, timestamp=_at(1)
        ),
        _exception_record(
            sync_script, request_key=None, trace_key="t3", route=None, timestamp=_at(2)
        ),
    ]


def test_measures_error_rate_counts_only_failures_on_routes(
    sync_script: ModuleType,
) -> None:
    group = _only_group(
        sync_script,
        _failures_with_and_without_a_route(sync_script),
        [_request_count(sync_script, "/<country_id>/calculate", 1)],
    )

    assert group.production.affected_requests == 3
    assert group.production.route_affected_requests == 1
    assert group.production.route_requests == 1
    assert group.production.error_rate == pytest.approx(1.0)


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
    assert parameters["chained_exception_pattern"]["parameterValue"]["value"] == (
        sync_script.CHAINED_EXCEPTION_PATTERN
    )
    for name, pattern in (
        ("double_quoted_pattern", sync_script.DOUBLE_QUOTED_PATTERN),
        ("single_quoted_pattern", sync_script.SINGLE_QUOTED_PATTERN),
        ("template_word_pattern", sync_script.TEMPLATE_WORD_PATTERN),
    ):
        assert parameters[name]["parameterValue"]["value"] == pattern
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
    assert (
        "  REGEXP_EXTRACT_ALL(\n"
        "    REGEXP_REPLACE(\n"
        f"      {stack}, @chained_exception_pattern, ''\n"
        "    ),\n"
        "    @frame_pattern\n"
        "  ) AS frames"
    ) in sql
    assert f"LENGTH({stack}) >= 16384" in sql
    assert sql.count("$.message") == 1
    assert (
        "          REGEXP_REPLACE(\n"
        "            REGEXP_REPLACE(\n"
        "              JSON_VALUE(json_payload, '$.message'), "
        "@double_quoted_pattern, ''\n"
        "            ),\n"
        "            @single_quoted_pattern,\n"
        "            r'\\1'\n"
        "          ),\n"
        "          @template_word_pattern\n"
    ) in sql
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


def _message_template(sync_script: ModuleType, message: str) -> str:
    """Build the template the way the query does, with RE2's ASCII word rules."""
    without_double_quotes = re.sub(sync_script.DOUBLE_QUOTED_PATTERN, "", message)
    without_quotes = re.sub(
        sync_script.SINGLE_QUOTED_PATTERN, r"\1", without_double_quotes
    )
    words = re.findall(sync_script.TEMPLATE_WORD_PATTERN, without_quotes, re.ASCII)
    return " ".join(word.lower() for word in words[:3])


def test_bigquery_template_keeps_words_around_an_apostrophe(
    sync_script: ModuleType,
) -> None:
    templates = {
        _message_template(sync_script, f"Can't load policy '{value}'")
        for value in ("alpha", "beta", "gamma")
    }

    assert templates == {"can t load"}


@pytest.mark.parametrize(
    ("message", "template"),
    [
        ("Failed to save 'report 12' for user", "failed to save"),
        ("'SENTINEL' could not be parsed", "could not be"),
        ('Missing "SENTINEL" in household input', "missing in household"),
        ("Timeout after 30s calling the simulation API", "timeout after calling"),
        ("The users' policies 'SENTINEL' failed", "the users policies"),
    ],
)
def test_bigquery_template_drops_quoted_values_and_partial_words(
    sync_script: ModuleType, message: str, template: str
) -> None:
    assert _message_template(sync_script, message) == template


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


# Issue rendering

PROJECT_ID = "policyengine-observability"


def _group(sync_script: ModuleType, records: list, request_counts=()) -> object:
    groups = sync_script.build_groups(
        records,
        list(request_counts),
        sync_script.reporting_window(REPORT_DATE),
        FINGERPRINT_KEY,
    )
    return groups[0]


def _render(sync_script: ModuleType, group: object) -> tuple[str, str]:
    window = sync_script.reporting_window(REPORT_DATE)
    return (
        sync_script.issue_title(group),
        sync_script.issue_body(group, window, PROJECT_ID),
    )


def _section(sync_script: ModuleType, body: str) -> str:
    start = body.index(sync_script.SECTION_START)
    end = body.index(sync_script.SECTION_END) + len(sync_script.SECTION_END)
    return body[start:end]


def _logs_query(url: str) -> tuple[str, dict[str, str]]:
    """Split a Logs Explorer URL into its decoded query and other settings."""
    parsed = urlsplit(url)
    settings = dict(
        segment.split("=", 1)
        for segment in parsed.path.split(";")[1:]
        if "=" in segment
    )
    return unquote(settings.pop("query")), settings


def test_render_title_names_the_exception_and_its_most_frequent_route(
    sync_script: ModuleType,
) -> None:
    group = _group(sync_script, [_exception_record(sync_script)])

    title, _ = _render(sync_script, group)

    assert title == (
        "[telemetry] policyengine-api: StaleDataError on `/<country_id>/report` "
        f"({group.fingerprint})"
    )


def test_render_title_for_a_logged_error(sync_script: ModuleType) -> None:
    route_group = _group(sync_script, [_message_record(sync_script)])
    operation_group = _group(
        sync_script,
        [
            _message_record(
                sync_script, route=None, operation_name="simulation.dispatch"
            )
        ],
    )

    assert sync_script.issue_title(route_group).startswith(
        "[telemetry] policyengine-api: logged error on `/<country_id>/report` ("
    )
    assert sync_script.issue_title(operation_group).startswith(
        "[telemetry] policyengine-api: logged error in `simulation.dispatch` ("
    )


def test_render_title_for_a_failed_request_without_an_exception(
    sync_script: ModuleType,
) -> None:
    group = _group(sync_script, [_failed_request_record(sync_script, status_code=502)])

    assert sync_script.issue_title(group) == (
        "[telemetry] policyengine-api: HTTP 502 without recorded exception on "
        f"`/<country_id>/report` ({group.fingerprint})"
    )


def test_render_title_without_a_route(sync_script: ModuleType) -> None:
    group = _group(
        sync_script,
        [
            _exception_record(
                sync_script,
                service_name="policyengine-stage12-us-worker",
                route=None,
            )
        ],
    )

    assert sync_script.issue_title(group) == (
        "[telemetry] policyengine-stage12-us-worker: StaleDataError "
        f"({group.fingerprint})"
    )


def test_render_body_marked_section_holds_the_measures_table(
    sync_script: ModuleType,
) -> None:
    records = [
        _exception_record(sync_script, request_key="r1", observability_key="o1"),
        _exception_record(sync_script, request_key="r2", timestamp=_at(2)),
        _exception_record(
            sync_script, request_key="s1", environment_name="staging", timestamp=_at(1)
        ),
    ]
    group = _group(
        sync_script,
        records,
        [_request_count(sync_script, "/<country_id>/report", 400)],
    )

    _, body = _render(sync_script, group)
    section = _section(sync_script, body)

    assert body.index(sync_script.SECTION_START) > 0
    assert f"`{group.fingerprint}`" in section
    assert "2026-10-20 00:00 EDT to 2026-10-21 00:00 EDT (24 hours)" in section
    assert "| Measure | Production | Staging |" in section
    assert "| Occurrences | 2 | 1 |" in section
    assert "| Affected requests | 2 | 1 |" in section
    assert "| Observability IDs | 1 | 0 |" in section
    assert (
        "| Error rate on affected routes | 0.50% (2 of 400 requests) | n/a |" in section
    )
    assert "| Occurrences per hour | 0.08 | 0.04 |" in section
    assert "| Occurrences per hour, previous 7 days | 0.00 | 0.00 |" in section
    assert (
        "| First seen in the last 8 days "
        "| 2026-10-20 12:00 EDT | 2026-10-20 13:00 EDT |" in section
    )
    assert "| Last seen | 2026-10-20 14:00 EDT | 2026-10-20 13:00 EDT |" in section
    assert "Related fingerprints: none" in section
    assert "https://console.cloud.google.com/logs/query;" in section


def test_render_error_rate_names_only_failures_on_routes(
    sync_script: ModuleType,
) -> None:
    group = _group(
        sync_script,
        _failures_with_and_without_a_route(sync_script),
        [_request_count(sync_script, "/<country_id>/calculate", 1)],
    )

    _, body = _render(sync_script, group)

    assert "| Error rate on affected routes | 100.00% (1 of 1 requests) | n/a |" in body


def test_render_body_lists_related_fingerprints(sync_script: ModuleType) -> None:
    records = [
        _exception_record(sync_script, trace_key="t1"),
        _message_record(
            sync_script, service_name="policyengine-simulation-entry", trace_key="t1"
        ),
    ]
    groups = sync_script.build_groups(
        records, [], sync_script.reporting_window(REPORT_DATE), FINGERPRINT_KEY
    )
    exception_group = next(group for group in groups if group.kind == "exception")
    other = exception_group.related_fingerprints[0]

    _, body = _render(sync_script, exception_group)

    assert f"Related fingerprints (sharing traces): `{other}`" in body


def test_render_body_state_comment_records_the_group_and_window(
    sync_script: ModuleType,
) -> None:
    group = _group(sync_script, [_exception_record(sync_script)])

    _, body = _render(sync_script, group)

    assert sync_script.parse_state(body) == {
        "algorithm": 1,
        "fingerprint": group.fingerprint,
        "kind": "exception",
        "window_end": "2026-10-21T04:00:00+00:00",
    }


def test_render_body_stays_under_the_github_limit(sync_script: ModuleType) -> None:
    # The longest route that still passes validation (195 characters).
    long_route = "/" + "/".join(["<segment_name>"] * 13)
    records = [
        _exception_record(
            sync_script,
            error_type="E" * 120,
            route=long_route,
            trace_key=f"t{index}",
            request_key=f"r{index}",
        )
        for index in range(4)
    ]
    records += [
        _message_record(
            sync_script,
            request_key=f"m{index}",
            trace_key=f"t{index}",
            message_template=f"template {index}",
            service_name="policyengine-simulation-entry",
        )
        for index in range(4)
    ]
    groups = sync_script.build_groups(
        records, [], sync_script.reporting_window(REPORT_DATE), FINGERPRINT_KEY
    )

    for group in groups:
        title, body = _render(sync_script, group)
        assert len(body) < 65_536
        assert len(title) <= 256


def test_render_logs_link_filters_exceptions_by_service_and_type(
    sync_script: ModuleType,
) -> None:
    group = _group(sync_script, [_exception_record(sync_script)])
    url = sync_script.logs_explorer_url(
        group, sync_script.reporting_window(REPORT_DATE), PROJECT_ID
    )

    query, settings = _logs_query(url)

    assert urlparse(url).query == "project=policyengine-observability"
    assert settings["storageScope"] == quote(
        "storage,projects/policyengine-observability/locations/global/"
        "buckets/policyengine-observability/views/_AllLogs",
        safe="",
    )
    assert query.splitlines() == [
        'jsonPayload.schema_version="policyengine.observability.v2"',
        'jsonPayload."service.name"="policyengine-api"',
        "severity>=ERROR",
        'jsonPayload."error.type"="StaleDataError"',
        'timestamp>="2026-10-20T04:00:00Z"',
        'timestamp<"2026-10-21T04:00:00Z"',
    ]
    for character in (" ", "\n", '"'):
        assert character not in url


def test_render_logs_link_filters_failed_requests_by_route_and_status(
    sync_script: ModuleType,
) -> None:
    group = _group(
        sync_script,
        [
            _failed_request_record(
                sync_script,
                service_name="policyengine-simulation-py1-2-3",
                route="/jobs/{job_id}",
                status_code=504,
            )
        ],
    )

    query, _ = _logs_query(
        sync_script.logs_explorer_url(
            group, sync_script.reporting_window(REPORT_DATE), PROJECT_ID
        )
    )

    assert query.splitlines()[1:5] == [
        'jsonPayload."service.name"=~"^policyengine-simulation-py[0-9]+-[0-9]+-[0-9]+$"',
        'jsonPayload."event.name"="request.completed"',
        'jsonPayload."http.route"="/jobs/{job_id}"',
        'jsonPayload."http.response.status_code"=504',
    ]


def test_render_logs_link_filters_logged_errors_by_route_or_operation(
    sync_script: ModuleType,
) -> None:
    window = sync_script.reporting_window(REPORT_DATE)
    route_group = _group(sync_script, [_message_record(sync_script)])
    operation_group = _group(
        sync_script,
        [
            _message_record(
                sync_script, route=None, operation_name="simulation.dispatch"
            )
        ],
    )

    route_query, _ = _logs_query(
        sync_script.logs_explorer_url(route_group, window, PROJECT_ID)
    )
    operation_query, _ = _logs_query(
        sync_script.logs_explorer_url(operation_group, window, PROJECT_ID)
    )

    assert 'jsonPayload."http.route"="/<country_id>/report"' in route_query
    assert "severity>=ERROR" in route_query
    assert 'jsonPayload."operation.name"="simulation.dispatch"' in operation_query


def _sentinel_row(sync_script: ModuleType, **overrides: object) -> dict[str, object]:
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


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"error_type": None},
        {"error_type": None, "event_name": "request.completed"},
        {"route": None},
    ],
)
def test_render_never_includes_values_from_records(
    sync_script: ModuleType, overrides: dict[str, object]
) -> None:
    record = sync_script.error_record_from_row(_sentinel_row(sync_script, **overrides))
    group = _group(sync_script, [record])
    window = sync_script.reporting_window(REPORT_DATE)

    title, body = _render(sync_script, group)
    url = sync_script.logs_explorer_url(group, window, PROJECT_ID)

    for output in (title, body, url, unquote(url)):
        assert "SENTINEL" not in output


# GitHub issue sync

REPOSITORY = "PolicyEngine/policyengine-api"
BOT = "github-actions[bot]"


class FakeGitHub:
    """An in-memory GitHub issues API with a clock that advances when it sleeps."""

    def __init__(
        self,
        sync_script: ModuleType,
        issues: list[dict] = (),
        labels: tuple[str, ...] = (),
        *,
        drop_created_labels: bool = False,
    ) -> None:
        self.sync_script = sync_script
        self.issues = {issue["number"]: dict(issue) for issue in issues}
        self.labels = set(labels)
        self.drop_created_labels = drop_created_labels
        self.failures: list[object] = []
        self.requests: list[tuple[float, object]] = []
        self.comments: dict[int, list[str]] = {}
        self.sleeps: list[float] = []
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def client(self) -> object:
        return self.sync_script.GitHubClient(
            REPOSITORY, "fake-github-token", self, sleep=self.sleep, clock=self.clock
        )

    @property
    def writes(self) -> list[tuple[float, object]]:
        return [entry for entry in self.requests if entry[1].method != "GET"]

    def _respond(self, payload: object, status: int = 200) -> object:
        return self.sync_script.HttpResponse(
            status=status, reason="OK", headers={}, body=json.dumps(payload).encode()
        )

    def __call__(self, request: object) -> object:
        self.requests.append((self.now, request))
        if request.method != "GET" and self.failures:
            return self.failures.pop(0)
        split = urlsplit(request.url)
        path = split.path.removeprefix(f"/repos/{REPOSITORY}")
        query = {name: values[0] for name, values in parse_qs(split.query).items()}
        body = json.loads(request.body) if request.body else None
        return self._route(request.method, path, query, body)

    def _route(self, method: str, path: str, query: dict, body: dict | None) -> object:
        parts = path.strip("/").split("/")
        if len(parts) > 1:
            return self._route_issue(method, int(parts[1]), parts[2:], body)
        if method == "GET" and parts == ["issues"]:
            issues = sorted(self.issues.values(), key=lambda issue: issue["number"])
            return self._respond(self._page(issues, query))
        if method == "GET":
            labels = [{"name": name} for name in sorted(self.labels)]
            return self._respond(self._page(labels, query))
        if parts == ["labels"]:
            # GitHub label names are unique regardless of case.
            if body["name"].casefold() in {name.casefold() for name in self.labels}:
                return self._respond({"message": "Validation Failed"}, status=422)
            self.labels.add(body["name"])
            return self._respond({"name": body["name"]}, status=201)
        return self._create(body)

    def _existing_label_names(self, requested: list[str]) -> list[str]:
        """Return the stored spelling of each label, as GitHub applies them."""
        stored = {name.casefold(): name for name in self.labels}
        return [stored.get(name.casefold(), name) for name in requested]

    def _route_issue(
        self, method: str, number: int, rest: list[str], body: dict
    ) -> object:
        if method == "PATCH":
            self.issues[number].update(body)
            return self._respond(self.issues[number])
        if rest == ["labels"]:
            names = {label["name"] for label in self.issues[number]["labels"]}
            if not self.drop_created_labels:
                names |= set(self._existing_label_names(body["labels"]))
            self.issues[number]["labels"] = [{"name": name} for name in sorted(names)]
            return self._respond(self.issues[number]["labels"])
        self.comments.setdefault(number, []).append(body["body"])
        return self._respond({"id": 1}, status=201)

    def _page(self, items: list, query: dict) -> list:
        page = int(query.get("page", "1"))
        size = int(query.get("per_page", "30"))
        return items[(page - 1) * size : page * size]

    def _create(self, body: dict) -> object:
        number = max(self.issues, default=0) + 1
        labels = (
            []
            if self.drop_created_labels
            else self._existing_label_names(body["labels"])
        )
        self.issues[number] = {
            "number": number,
            "title": body["title"],
            "body": body["body"],
            "state": "open",
            "state_reason": None,
            "closed_at": None,
            "labels": [{"name": name} for name in labels],
            "user": {"login": BOT},
        }
        return self._respond(self.issues[number], status=201)


def _bot_issue(number: int, **fields: object) -> dict:
    issue = {
        "number": number,
        "title": f"Issue {number}",
        "body": "",
        "state": "open",
        "state_reason": None,
        "closed_at": None,
        "labels": [],
        "user": {"login": BOT},
    }
    issue.update(fields)
    return issue


def _failures(
    sync_script: ModuleType,
    count: int,
    *,
    request_key_prefix: str = "r",
    **fields: object,
) -> list:
    return [
        _exception_record(
            sync_script,
            request_key=f"{request_key_prefix}{index}",
            timestamp=_at(index),
            **fields,
        )
        for index in range(count)
    ]


def _groups(sync_script: ModuleType, records: list) -> list:
    return sync_script.build_groups(
        records, [], sync_script.reporting_window(REPORT_DATE), FINGERPRINT_KEY
    )


def _sync(sync_script: ModuleType, groups: list, github: FakeGitHub, *, dry_run=False):
    return sync_script.sync_issues(
        groups,
        sync_script.reporting_window(REPORT_DATE),
        PROJECT_ID,
        github.client(),
        dry_run=dry_run,
    )


def _existing_issue(
    sync_script: ModuleType, group: object, number: int = 7, **fields: object
) -> dict:
    """Return the issue the job opened for ``group`` on an earlier day."""
    earlier = sync_script.reporting_window(REPORT_DATE - timedelta(days=1))
    issue = _bot_issue(
        number,
        title=sync_script.issue_title(group),
        body=sync_script.issue_body(group, earlier, PROJECT_ID),
    )
    issue.update(fields)
    return issue


def test_sync_lists_open_and_closed_issues_from_the_bot_page_by_page(
    sync_script: ModuleType,
) -> None:
    github = FakeGitHub(sync_script, [_bot_issue(number) for number in range(1, 151)])

    _sync(sync_script, [], github)

    listing = [
        parse_qs(urlsplit(request.url).query)
        for _, request in github.requests
        if urlsplit(request.url).path.endswith("/issues")
    ]
    assert len(listing) == 2
    assert listing[0]["creator"] == [BOT]
    assert listing[0]["state"] == ["all"]
    assert listing[0]["per_page"] == ["100"]
    assert [query["page"] for query in listing] == [["1"], ["2"]]


def test_sync_opens_an_issue_at_three_production_occurrences_in_two_requests(
    sync_script: ModuleType,
) -> None:
    eligible = _failures(sync_script, 3)
    # Three failures that all affected the request with observability ID o1.
    one_request = [
        _exception_record(
            sync_script,
            error_type="KeyError",
            request_key=None,
            trace_key=None,
            observability_key="o1",
            timestamp=_at(index),
        )
        for index in range(3)
    ]
    too_few = _failures(
        sync_script, 2, request_key_prefix="few", error_type="TypeError"
    )
    groups = _groups(sync_script, eligible + one_request + too_few)
    github = FakeGitHub(sync_script)

    result = _sync(sync_script, groups, github)

    created = list(github.issues.values())
    eligible_group = next(
        group for group in groups if group.error_type == "StaleDataError"
    )
    assert [issue["title"] for issue in created] == [
        sync_script.issue_title(eligible_group)
    ]
    assert created[0]["labels"] == [
        {"name": "telemetry-error"},
        {"name": "service: policyengine-api"},
    ]
    actions = {action.fingerprint: action.action for action in result.actions}
    assert sorted(actions.values()) == ["below-threshold", "below-threshold", "created"]


def test_sync_never_opens_an_issue_for_a_staging_only_group(
    sync_script: ModuleType,
) -> None:
    groups = _groups(
        sync_script, _failures(sync_script, 10, environment_name="staging")
    )
    github = FakeGitHub(sync_script)

    result = _sync(sync_script, groups, github)

    assert github.issues == {}
    assert result.actions[0].action == "below-threshold"


def test_sync_opens_at_most_five_issues_in_order_of_production_volume(
    sync_script: ModuleType,
) -> None:
    records = []
    for index in range(7):
        records += _failures(
            sync_script,
            3 + index,
            request_key_prefix=f"g{index}-",
            error_type=f"Error{index}",
        )
    groups = _groups(sync_script, records)
    github = FakeGitHub(sync_script)

    result = _sync(sync_script, groups, github)

    titles = [issue["title"] for issue in github.issues.values()]
    assert [title.split(": ")[1].split(" ")[0] for title in titles] == [
        "Error6",
        "Error5",
        "Error4",
        "Error3",
        "Error2",
    ]
    assert result.deferred == 2
    assert [action.action for action in result.actions].count("deferred") == 2


def test_sync_replaces_only_the_marked_section_and_never_the_title(
    sync_script: ModuleType,
) -> None:
    group = _groups(sync_script, _failures(sync_script, 3))[0]
    issue = _existing_issue(sync_script, group, title="Renamed by a person")
    issue["body"] = f"Notes before.\n\n{issue['body']}\nNotes after.\n"
    github = FakeGitHub(sync_script, [issue])

    result = _sync(sync_script, [group], github)

    patch = json.loads(github.writes[0][1].body)
    expected_section = sync_script.issue_section(
        group, sync_script.reporting_window(REPORT_DATE), PROJECT_ID
    )
    assert list(patch) == ["body"]
    assert patch["body"].startswith("Notes before.\n\n")
    assert patch["body"].endswith("\nNotes after.\n")
    assert expected_section in patch["body"]
    assert github.issues[7]["title"] == "Renamed by a person"
    assert result.actions[0].action == "updated"
    assert result.actions[0].issue_number == 7


def test_sync_does_not_write_when_the_section_is_unchanged(
    sync_script: ModuleType,
) -> None:
    group = _groups(sync_script, _failures(sync_script, 3))[0]
    github = FakeGitHub(sync_script, [_existing_issue(sync_script, group)])

    _sync(sync_script, [group], github)
    first_run_writes = len(github.writes)
    second = _sync(sync_script, [group], github)

    assert first_run_writes == 1
    assert len(github.writes) == 1
    assert second.actions[0].action == "unchanged"


def test_sync_adds_a_deleted_section_back_at_the_end(sync_script: ModuleType) -> None:
    group = _groups(sync_script, _failures(sync_script, 3))[0]
    issue = _existing_issue(sync_script, group, body="Only human notes now.")
    github = FakeGitHub(sync_script, [issue])

    _sync(sync_script, [group], github)

    body = github.issues[7]["body"]
    assert body.startswith("Only human notes now.\n\n")
    assert body.rstrip().endswith(sync_script.SECTION_END)
    assert len(github.issues) == 1


def test_sync_ignores_issues_opened_by_other_authors(sync_script: ModuleType) -> None:
    group = _groups(sync_script, _failures(sync_script, 3))[0]
    person_issue = _existing_issue(sync_script, group, user={"login": "someone"})
    github = FakeGitHub(sync_script, [person_issue])

    _sync(sync_script, [group], github)

    assert github.issues[7]["body"] == person_issue["body"]
    assert len(github.issues) == 2


def test_sync_reopens_a_completed_issue_when_production_failures_return(
    sync_script: ModuleType,
) -> None:
    group = _groups(sync_script, _failures(sync_script, 4))[0]
    closed_at = (WINDOW_NOON - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    issue = _existing_issue(
        sync_script,
        group,
        state="closed",
        state_reason="completed",
        closed_at=closed_at,
    )
    github = FakeGitHub(sync_script, [issue], labels=("telemetry-error",))

    result = _sync(sync_script, [group], github)

    reopened = github.issues[7]
    assert reopened["state"] == "open"
    assert reopened["state_reason"] == "reopened"
    assert {"name": "regression"} in reopened["labels"]
    assert "regression" in github.labels
    assert github.comments[7] == [
        "Production failures returned after this issue was closed: 4 occurrences "
        "in 4 requests since 2026-10-19 12:00 EDT, 24 hours after it was closed."
    ]
    assert result.actions[0].action == "reopened"


def test_sync_treats_an_issue_closed_without_a_reason_as_completed(
    sync_script: ModuleType,
) -> None:
    group = _groups(sync_script, _failures(sync_script, 3))[0]
    closed_at = (WINDOW_NOON - timedelta(days=2)).isoformat()
    issue = _existing_issue(
        sync_script, group, state="closed", state_reason=None, closed_at=closed_at
    )
    github = FakeGitHub(sync_script, [issue])

    result = _sync(sync_script, [group], github)

    assert github.issues[7]["state"] == "open"
    assert result.actions[0].action == "reopened"


def test_sync_keeps_a_completed_issue_closed_within_24_hours_of_closing(
    sync_script: ModuleType,
) -> None:
    group = _groups(sync_script, _failures(sync_script, 4))[0]
    closed_at = (WINDOW_NOON - timedelta(hours=12)).isoformat()
    issue = _existing_issue(
        sync_script,
        group,
        state="closed",
        state_reason="completed",
        closed_at=closed_at,
    )
    github = FakeGitHub(sync_script, [issue])

    result = _sync(sync_script, [group], github)

    assert github.issues[7]["state"] == "closed"
    assert 7 not in github.comments
    assert (
        sync_script.issue_section(
            group, sync_script.reporting_window(REPORT_DATE), PROJECT_ID
        )
        in github.issues[7]["body"]
    )
    assert result.actions[0].action == "updated"


@pytest.mark.parametrize("reason", ["not_planned", "duplicate"])
def test_sync_updates_but_never_reopens_not_planned_or_duplicate_issues(
    sync_script: ModuleType, reason: str
) -> None:
    group = _groups(sync_script, _failures(sync_script, 10))[0]
    closed_at = (WINDOW_NOON - timedelta(days=5)).isoformat()
    issue = _existing_issue(
        sync_script, group, state="closed", state_reason=reason, closed_at=closed_at
    )
    github = FakeGitHub(sync_script, [issue])

    result = _sync(sync_script, [group], github)

    assert github.issues[7]["state"] == "closed"
    assert result.actions[0].action == "updated"
    assert len(github.issues) == 1


def test_sync_keeps_a_newer_report_instead_of_overwriting_it(
    sync_script: ModuleType,
) -> None:
    group = _groups(sync_script, _failures(sync_script, 3))[0]
    later = sync_script.reporting_window(REPORT_DATE + timedelta(days=1))
    issue = _bot_issue(
        7,
        title=sync_script.issue_title(group),
        body=sync_script.issue_body(group, later, PROJECT_ID),
    )
    github = FakeGitHub(sync_script, [issue])

    result = _sync(sync_script, [group], github)

    assert github.writes == []
    assert result.actions[0].action == "kept-newer"


def test_sync_creates_missing_labels_before_opening_issues(
    sync_script: ModuleType,
) -> None:
    groups = _groups(sync_script, _failures(sync_script, 3))
    github = FakeGitHub(sync_script, labels=("telemetry-error",))

    _sync(sync_script, groups, github)

    created_labels = [
        json.loads(request.body)["name"]
        for _, request in github.writes
        if urlsplit(request.url).path.endswith("/labels")
    ]
    assert created_labels == ["service: policyengine-api"]


def test_sync_uses_existing_labels_whatever_their_case(
    sync_script: ModuleType,
) -> None:
    groups = _groups(sync_script, _failures(sync_script, 3))
    github = FakeGitHub(
        sync_script, labels=("Telemetry-Error", "Service: Policyengine-Api")
    )

    _sync(sync_script, groups, github)

    created_labels = [
        request
        for _, request in github.writes
        if urlsplit(request.url).path.endswith("/labels")
    ]
    assert created_labels == []
    assert github.issues[1]["labels"] == [
        {"name": "Telemetry-Error"},
        {"name": "Service: Policyengine-Api"},
    ]


def test_sync_reopens_with_an_existing_regression_label_of_another_case(
    sync_script: ModuleType,
) -> None:
    group = _groups(sync_script, _failures(sync_script, 4))[0]
    closed_at = (WINDOW_NOON - timedelta(days=2)).isoformat()
    issue = _existing_issue(
        sync_script,
        group,
        state="closed",
        state_reason="completed",
        closed_at=closed_at,
    )
    github = FakeGitHub(sync_script, [issue], labels=("Regression",))

    result = _sync(sync_script, [group], github)

    assert result.actions[0].action == "reopened"
    assert {"name": "Regression"} in github.issues[7]["labels"]
    assert github.labels == {"Regression"}


def test_sync_adds_labels_a_create_response_is_missing(
    sync_script: ModuleType,
) -> None:
    groups = _groups(sync_script, _failures(sync_script, 3))
    github = FakeGitHub(sync_script, drop_created_labels=True)

    with pytest.raises(sync_script.GitHubError, match="labels"):
        _sync(sync_script, groups, github)

    added = [
        request
        for _, request in github.writes
        if urlsplit(request.url).path.endswith("/issues/1/labels")
    ]
    assert len(added) == 1


def test_sync_writes_one_at_a_time_at_least_a_second_apart(
    sync_script: ModuleType,
) -> None:
    records = []
    for index in range(3):
        records += _failures(
            sync_script, 3, request_key_prefix=f"g{index}-", error_type=f"Error{index}"
        )
    github = FakeGitHub(sync_script)

    _sync(sync_script, _groups(sync_script, records), github)

    write_times = [moment for moment, _ in github.writes]
    assert len(write_times) == 5
    assert all(
        later - earlier >= 1.0 for earlier, later in itertools.pairwise(write_times)
    )


@pytest.mark.parametrize("status", [403, 429])
def test_sync_waits_for_retry_after_on_rate_limits(
    sync_script: ModuleType, status: int
) -> None:
    groups = _groups(sync_script, _failures(sync_script, 3))
    github = FakeGitHub(
        sync_script, labels=("telemetry-error", "service: policyengine-api")
    )
    github.failures = [
        sync_script.HttpResponse(
            status=status, reason="Forbidden", headers={"retry-after": "7"}, body=b"{}"
        )
    ]

    _sync(sync_script, groups, github)

    assert 7 in github.sleeps
    assert len(github.issues) == 1


def test_sync_stops_after_three_rate_limit_retries(sync_script: ModuleType) -> None:
    groups = _groups(sync_script, _failures(sync_script, 3))
    github = FakeGitHub(
        sync_script, labels=("telemetry-error", "service: policyengine-api")
    )
    limited = sync_script.HttpResponse(
        status=429, reason="Too Many Requests", headers={"retry-after": "2"}, body=b"{}"
    )
    github.failures = [limited] * 4

    with pytest.raises(sync_script.GitHubError) as raised:
        _sync(sync_script, groups, github)

    assert str(raised.value) == "GitHub request failed: HTTP 429 Too Many Requests"
    assert github.sleeps.count(2) == 3


def test_sync_reports_a_forbidden_write_without_retrying(
    sync_script: ModuleType,
) -> None:
    groups = _groups(sync_script, _failures(sync_script, 3))
    github = FakeGitHub(
        sync_script, labels=("telemetry-error", "service: policyengine-api")
    )
    github.failures = [
        sync_script.HttpResponse(
            status=403,
            reason="Forbidden",
            headers={},
            body=b'{"message": "SENTINEL Resource not accessible"}',
        )
    ]

    with pytest.raises(sync_script.GitHubError) as raised:
        _sync(sync_script, groups, github)

    assert str(raised.value) == "GitHub request failed: HTTP 403 Forbidden"
    assert len(github.writes) == 1


def test_sync_dry_run_makes_no_write_calls(sync_script: ModuleType) -> None:
    eligible = _groups(sync_script, _failures(sync_script, 3))[0]
    existing = _groups(sync_script, _failures(sync_script, 3, error_type="KeyError"))[0]
    github = FakeGitHub(sync_script, [_existing_issue(sync_script, existing)])

    result = _sync(sync_script, [eligible, existing], github, dry_run=True)

    assert github.writes == []
    assert sorted(action.action for action in result.actions) == ["created", "updated"]


# End-to-end run and public output

ERROR_RECORD_FIELDS = [
    {"name": "timestamp", "type": "TIMESTAMP"},
    {"name": "service_name", "type": "STRING"},
    {"name": "environment_name", "type": "STRING"},
    {"name": "event_name", "type": "STRING"},
    {"name": "error_type", "type": "STRING"},
    {"name": "error_handled", "type": "STRING"},
    {"name": "frames", "type": "STRING", "mode": "REPEATED"},
    {"name": "stack_truncated", "type": "BOOLEAN"},
    {"name": "message_template", "type": "STRING"},
    {"name": "attribute_error_type", "type": "STRING"},
    {"name": "failure_category", "type": "STRING"},
    {"name": "route", "type": "STRING"},
    {"name": "status_code", "type": "STRING"},
    {"name": "operation_name", "type": "STRING"},
    {"name": "request_key", "type": "STRING"},
    {"name": "observability_key", "type": "STRING"},
    {"name": "trace_key", "type": "STRING"},
]
REQUEST_COUNT_FIELDS = [
    {"name": "service_name", "type": "STRING"},
    {"name": "environment_name", "type": "STRING"},
    {"name": "route", "type": "STRING"},
    {"name": "requests", "type": "INTEGER"},
]
SCHEDULED_RUN_TIME = datetime(2026, 10, 21, 0, 45, tzinfo=EASTERN)


def _microseconds(moment: datetime) -> str:
    return str((moment - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1))


def _error_row(**overrides: object) -> list[object]:
    values: dict[str, object] = {
        "timestamp": _microseconds(WINDOW_NOON),
        "service_name": "policyengine-api",
        "environment_name": "production",
        "event_name": "exception.recorded",
        "error_type": "StaleDataError",
        "error_handled": "false",
        "frames": list(APPLICATION_FRAMES),
        "stack_truncated": "false",
        "message_template": None,
        "attribute_error_type": None,
        "failure_category": None,
        "route": "/<country_id>/report",
        "status_code": "500",
        "operation_name": None,
        "request_key": "r1",
        "observability_key": None,
        "trace_key": "t1",
    }
    values.update(overrides)
    return [values[field["name"]] for field in ERROR_RECORD_FIELDS]


class FakeBigQuery:
    """Answers the error-record and request-count queries with fixed rows."""

    def __init__(
        self,
        sync_script: ModuleType,
        error_rows: list[list[object]],
        count_rows: list[list[object]] = (),
    ) -> None:
        self.sync_script = sync_script
        self.error_rows = error_rows
        self.count_rows = list(count_rows)
        self.requests: list[object] = []

    def __call__(self, request: object) -> object:
        self.requests.append(request)
        label = json.loads(request.body)["labels"]["query"]
        if label == "error-records":
            response = _query_response(ERROR_RECORD_FIELDS, self.error_rows)
        else:
            response = _query_response(REQUEST_COUNT_FIELDS, self.count_rows)
        return _json_response(self.sync_script, response)

    def json_body(self, index: int) -> dict:
        return json.loads(self.requests[index].body)


def _environment(tmp_path: Path, **overrides: str) -> dict[str, str]:
    environment = {
        "GOOGLE_OAUTH_ACCESS_TOKEN": ACCESS_TOKEN,
        "GITHUB_TOKEN": "fake-github-token",
        "GITHUB_REPOSITORY": REPOSITORY,
        "TELEMETRY_ERROR_FINGERPRINT_KEY": "f" * 64,
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
    }
    environment.update(overrides)
    return {name: value for name, value in environment.items() if value}


def _run_main(
    sync_script: ModuleType,
    tmp_path: Path,
    bigquery: object,
    github: FakeGitHub,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    runtime = sync_script.Runtime(
        environ=_environment(tmp_path) if environment is None else environment,
        bigquery_transport=bigquery,
        github_transport=github,
        now=lambda: SCHEDULED_RUN_TIME,
        sleep=github.sleep,
        clock=github.clock,
        stdout=stdout,
        stderr=stderr,
    )
    exit_code = sync_script.main(
        ["--project-id", PROJECT_ID, *arguments], runtime=runtime
    )
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _three_failures(**overrides: object) -> list[list[object]]:
    return [
        _error_row(
            request_key=f"r{index}",
            timestamp=_microseconds(_at(index)),
            **overrides,
        )
        for index in range(3)
    ]


def test_main_queries_groups_and_opens_issues_for_the_previous_day(
    sync_script: ModuleType, tmp_path: Path
) -> None:
    bigquery = FakeBigQuery(
        sync_script,
        _three_failures(),
        [["policyengine-api", "production", "/<country_id>/report", "600"]],
    )
    github = FakeGitHub(sync_script)

    exit_code, stdout, stderr = _run_main(sync_script, tmp_path, bigquery, github)

    assert exit_code == 0, stderr
    issue = github.issues[1]
    assert "StaleDataError" in issue["title"]
    assert (
        "| Error rate on affected routes | 0.50% (3 of 600 requests) | n/a |"
        in (issue["body"])
    )
    window_end = _sent_parameters(bigquery)["window_end"]["parameterValue"]
    assert window_end["value"] == "2026-10-21 04:00:00+00:00"
    summary = (tmp_path / "summary.md").read_text()
    fingerprint = issue["title"].rsplit("(", 1)[1].rstrip(")")
    assert (
        f"| `{fingerprint}` | exception | `policyengine-api` | 3 | 0 | #1 | created |"
        in summary
    )
    assert summary in stdout


def test_main_dry_run_reports_actions_without_writing(
    sync_script: ModuleType, tmp_path: Path
) -> None:
    github = FakeGitHub(sync_script)

    exit_code, stdout, _ = _run_main(
        sync_script,
        tmp_path,
        FakeBigQuery(sync_script, _three_failures()),
        github,
        "--dry-run",
    )

    assert exit_code == 0
    assert github.writes == []
    assert "Dry run: no issues were changed." in stdout
    assert "| - | created |" in stdout


def test_main_reports_the_requested_day(
    sync_script: ModuleType, tmp_path: Path
) -> None:
    bigquery = FakeBigQuery(sync_script, [])

    exit_code, stdout, _ = _run_main(
        sync_script,
        tmp_path,
        bigquery,
        FakeGitHub(sync_script),
        "--report-date",
        "2026-10-15",
    )

    assert exit_code == 0
    window_end = _sent_parameters(bigquery)["window_end"]["parameterValue"]
    assert window_end["value"] == "2026-10-16 04:00:00+00:00"
    assert "## Telemetry error issues for 2026-10-15" in stdout
    assert "No error groups had failures in the window." in stdout


def test_main_rejects_a_day_that_has_not_ended(
    sync_script: ModuleType, tmp_path: Path
) -> None:
    exit_code, stdout, stderr = _run_main(
        sync_script,
        tmp_path,
        FakeBigQuery(sync_script, []),
        FakeGitHub(sync_script),
        "--report-date",
        "2026-10-21",
    )

    assert exit_code == 1
    assert stdout == ""
    assert stderr == (
        "configuration failed: ConfigurationError "
        "(2026-10-21 has not ended in US Eastern time)\n"
    )


def test_main_names_missing_environment_variables_without_values(
    sync_script: ModuleType, tmp_path: Path
) -> None:
    environment = _environment(
        tmp_path, GITHUB_TOKEN="", TELEMETRY_ERROR_FINGERPRINT_KEY=""
    )

    exit_code, _, stderr = _run_main(
        sync_script,
        tmp_path,
        FakeBigQuery(sync_script, []),
        FakeGitHub(sync_script),
        environment=environment,
    )

    assert exit_code == 1
    assert stderr == (
        "configuration failed: ConfigurationError (missing environment variables: "
        "GITHUB_TOKEN, TELEMETRY_ERROR_FINGERPRINT_KEY)\n"
    )


def test_main_rejects_a_short_fingerprint_key_without_printing_it(
    sync_script: ModuleType, tmp_path: Path
) -> None:
    environment = _environment(
        tmp_path, TELEMETRY_ERROR_FINGERPRINT_KEY="SENTINEL-short-key"
    )

    exit_code, stdout, stderr = _run_main(
        sync_script,
        tmp_path,
        FakeBigQuery(sync_script, []),
        FakeGitHub(sync_script),
        environment=environment,
    )

    assert exit_code == 1
    assert "at least 32 characters" in stderr
    assert "SENTINEL" not in stdout + stderr


def test_main_reports_an_api_failure_by_stage_class_and_status_only(
    sync_script: ModuleType, tmp_path: Path
) -> None:
    error_body = {
        "error": {
            "message": "SENTINEL echoed value",
            "errors": [{"reason": "backendError", "message": "SENTINEL"}],
        }
    }
    failing = FakeTransport(
        sync_script,
        [_json_response(sync_script, error_body, status=500, reason="SENTINEL")],
    )

    exit_code, stdout, stderr = _run_main(
        sync_script, tmp_path, failing, FakeGitHub(sync_script)
    )

    assert exit_code == 1
    assert stdout == ""
    assert stderr == (
        "query error records failed: BigQueryError (HTTP 500 backendError)\n"
    )


def test_main_reports_an_unexpected_exception_by_class_only(
    sync_script: ModuleType, tmp_path: Path
) -> None:
    def broken_transport(request: object) -> object:
        message = "SENTINEL connection detail"
        raise RuntimeError(message)

    exit_code, _, stderr = _run_main(
        sync_script, tmp_path, broken_transport, FakeGitHub(sync_script)
    )

    assert exit_code == 1
    assert stderr == "query error records failed: RuntimeError\n"


def test_main_reports_a_github_failure_by_stage(
    sync_script: ModuleType, tmp_path: Path
) -> None:
    github = FakeGitHub(sync_script)
    github.failures = [
        sync_script.HttpResponse(
            status=403, reason="Forbidden", headers={}, body=b'{"message": "SENTINEL"}'
        )
    ]

    exit_code, _, stderr = _run_main(
        sync_script, tmp_path, FakeBigQuery(sync_script, _three_failures()), github
    )

    assert exit_code == 1
    assert stderr == "sync issues failed: GitHubError (HTTP 403 Forbidden)\n"


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"error_type": None},
        {"error_type": None, "event_name": "request.completed"},
    ],
)
def test_main_never_publishes_values_from_records(
    sync_script: ModuleType, tmp_path: Path, overrides: dict[str, object]
) -> None:
    sentinel_values = {
        name: value
        for name, value in _sentinel_row(sync_script, **overrides).items()
        if name not in {"timestamp", "environment_name", "frames", "stack_truncated"}
    }
    sentinel_values["stack_truncated"] = "true"
    sentinel_values["frames"] = ['/app/SENTINEL.py", line 1, in SENTINEL']
    rows = [
        _error_row(
            **{
                **sentinel_values,
                "request_key": f"SENTINEL request {index}",
                "timestamp": _microseconds(_at(index)),
            }
        )
        for index in range(3)
    ]
    count_rows = [["SENTINEL service", "production", "SENTINEL route", "10"]]
    github = FakeGitHub(sync_script)

    exit_code, stdout, stderr = _run_main(
        sync_script, tmp_path, FakeBigQuery(sync_script, rows, count_rows), github
    )

    assert exit_code == 0, stderr
    assert len(github.issues) == 1
    published = [
        stdout,
        stderr,
        (tmp_path / "summary.md").read_text(),
        *(issue["title"] for issue in github.issues.values()),
        *(issue["body"] for issue in github.issues.values()),
    ]
    for text in published:
        assert "SENTINEL" not in unquote(text)


# Workflow and wrapper

WORKFLOW_PATH = REPO / ".github" / "workflows" / "telemetry-error-issues.yml"
WRAPPER_PATH = REPO / ".github" / "scripts" / "sync_telemetry_error_issues.sh"
WRAPPER_ENVIRONMENT = {
    "GOOGLE_OAUTH_ACCESS_TOKEN": "fake-access-token",
    "GITHUB_TOKEN": "fake-github-token",
    "GITHUB_REPOSITORY": REPOSITORY,
    "TELEMETRY_ERROR_FINGERPRINT_KEY": "f" * 64,
    "OBSERVABILITY_PROJECT_ID": PROJECT_ID,
}


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _sync_job() -> dict:
    return _workflow()["jobs"]["sync"]


def _step(name: str) -> dict:
    return next(step for step in _sync_job()["steps"] if step["name"] == name)


def test_workflow_runs_at_00_45_eastern_and_on_request() -> None:
    # PyYAML reads the bare key "on" as the boolean True.
    triggers = _workflow()[True]

    assert triggers["schedule"] == [
        {"cron": "45 0 * * *", "timezone": "America/New_York"}
    ]
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["dry_run"]["type"] == "boolean"
    assert inputs["dry_run"]["default"] is True
    assert inputs["report_date"]["type"] == "string"
    assert inputs["report_date"]["default"] == ""


def test_workflow_job_is_limited_to_master_in_its_environment() -> None:
    workflow = _workflow()
    job = _sync_job()

    assert workflow["concurrency"] == {
        "group": "telemetry-error-issues",
        "cancel-in-progress": False,
    }
    assert job["if"] == "github.repository == 'PolicyEngine/policyengine-api'"
    assert job["environment"] == "telemetry-error-issues"
    assert job["timeout-minutes"] == 15
    assert job["permissions"] == {
        "contents": "read",
        "issues": "write",
        "id-token": "write",
    }
    assert job["steps"][0] == {
        "name": "Require master branch",
        "if": "github.ref != 'refs/heads/master'",
        "run": "exit 1",
    }


def test_workflow_authenticates_as_the_report_service_account() -> None:
    auth = _step("Authenticate to Google Cloud")

    assert auth["id"] == "auth"
    assert auth["uses"] == "google-github-actions/auth@v2"
    assert auth["with"] == {
        "workload_identity_provider": "${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}",
        "service_account": "${{ vars.TELEMETRY_ERROR_ISSUES_SERVICE_ACCOUNT }}",
        "token_format": "access_token",
        "create_credentials_file": False,
    }
    assert _step("Set up Python")["with"] == {"python-version": "3.12"}


def test_workflow_passes_settings_to_the_wrapper() -> None:
    sync = _step("Sync telemetry error issues")

    assert sync["run"] == "bash .github/scripts/sync_telemetry_error_issues.sh"
    assert sync["env"] == {
        "GOOGLE_OAUTH_ACCESS_TOKEN": "${{ steps.auth.outputs.access_token }}",
        "GITHUB_TOKEN": "${{ github.token }}",
        "TELEMETRY_ERROR_FINGERPRINT_KEY": (
            "${{ secrets.TELEMETRY_ERROR_FINGERPRINT_KEY }}"
        ),
        "OBSERVABILITY_PROJECT_ID": "${{ vars.OBSERVABILITY_PROJECT_ID }}",
        # A scheduled run has no inputs, so it is never a dry run.
        "DRY_RUN": "${{ github.event_name == 'workflow_dispatch' && inputs.dry_run }}",
        "REPORT_DATE": "${{ inputs.report_date }}",
    }


def _run_wrapper(
    tmp_path: Path, environment: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], list[str] | None]:
    """Run the wrapper with a fake python3 that records its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "python-arguments.txt"
    fake_python = bin_dir / "python3"
    fake_python.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{calls}"\n')
    fake_python.chmod(0o755)
    result = subprocess.run(
        ["bash", str(WRAPPER_PATH)],
        cwd=REPO,
        env={"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", **environment},
        text=True,
        capture_output=True,
        check=False,
    )
    arguments = calls.read_text().splitlines() if calls.exists() else None
    return result, arguments


def test_wrapper_passes_bash_syntax_checking() -> None:
    result = subprocess.run(
        ["bash", "-n", str(WRAPPER_PATH)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


def test_wrapper_runs_the_report_for_the_project(tmp_path: Path) -> None:
    result, arguments = _run_wrapper(tmp_path, WRAPPER_ENVIRONMENT)

    assert result.returncode == 0, result.stderr
    assert arguments == [str(SCRIPT_PATH), "--project-id", PROJECT_ID]


def test_wrapper_masks_the_access_token_and_fingerprint_key(tmp_path: Path) -> None:
    result, _ = _run_wrapper(tmp_path, WRAPPER_ENVIRONMENT)

    assert result.stdout.splitlines() == [
        "::add-mask::fake-access-token",
        f"::add-mask::{'f' * 64}",
    ]


def test_wrapper_adds_dry_run_and_report_date_when_set(tmp_path: Path) -> None:
    environment = {
        **WRAPPER_ENVIRONMENT,
        "DRY_RUN": "true",
        "REPORT_DATE": "2026-10-15",
    }

    result, arguments = _run_wrapper(tmp_path, environment)

    assert result.returncode == 0, result.stderr
    assert arguments == [
        str(SCRIPT_PATH),
        "--project-id",
        PROJECT_ID,
        "--dry-run",
        "--report-date",
        "2026-10-15",
    ]


def test_wrapper_runs_live_when_dry_run_is_false(tmp_path: Path) -> None:
    environment = {**WRAPPER_ENVIRONMENT, "DRY_RUN": "false", "REPORT_DATE": ""}

    _, arguments = _run_wrapper(tmp_path, environment)

    assert arguments == [str(SCRIPT_PATH), "--project-id", PROJECT_ID]


@pytest.mark.parametrize("missing", sorted(WRAPPER_ENVIRONMENT))
def test_wrapper_fails_before_running_when_a_variable_is_missing(
    tmp_path: Path, missing: str
) -> None:
    environment = {
        name: value for name, value in WRAPPER_ENVIRONMENT.items() if name != missing
    }

    result, arguments = _run_wrapper(tmp_path, environment)

    assert result.returncode != 0
    assert f"{missing} is required" in result.stderr
    assert arguments is None
    assert result.stdout == ""
