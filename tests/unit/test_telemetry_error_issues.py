"""Tests for .github/scripts/sync_telemetry_error_issues.py."""

from __future__ import annotations

import functools
import importlib.util
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
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
  File "/opt/venv/lib/python3.12/site-packages/flask/app.py", line 880, in full_dispatch_request
    rv = self.dispatch_request()
         ^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/policyengine_api/routes/report_routes.py", line 41, in create_report
    return service.create(payload)
  File "/app/policyengine_api/services/report_service.py", line 88, in create
    session.flush()
  File "/opt/venv/lib/python3.12/site-packages/sqlalchemy/orm/session.py", line 4331, in flush
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
        "flask/app.py:full_dispatch_request",
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
        "flask/app.py:full_dispatch_request",
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
        '/opt/venv/lib/python3.12/site-packages/sqlalchemy/orm/f.py", line 6, in raises',
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
