"""Tests for telemetry_error_issues.normalization: names, frames and public values."""

from __future__ import annotations

import re

import pytest
from telemetry_error_issues import normalization
from telemetry_error_issues.bigquery import FRAME_PATTERN
from telemetry_error_issues.normalization import (
    fingerprint_frames,
    frame_location,
    normalize_path,
    public_error_type,
    public_family,
    public_operation,
    public_route,
    public_status,
    service_family,
)

from tests.unit.telemetry_error_issues.report_support import (
    chained_stack,
    extract_frames,
)

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
    service_name: str, family: str
) -> None:
    assert service_family(service_name) == family


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
    environment_name: str | None, environment_class: str
) -> None:
    assert normalization.environment_class(environment_name) == environment_class


def test_frames_pattern_has_one_capturing_group_for_bigquery() -> None:
    assert re.compile(FRAME_PATTERN).groups == 1


def test_frames_pattern_extracts_frame_headers_without_source_or_message() -> None:
    frames = extract_frames(STANDARD_STACK)

    assert [frame_location(frame) for frame in frames] == [
        ("flask/app.py", "dispatch_request"),
        ("policyengine_api/routes/report_routes.py", "create_report"),
        ("policyengine_api/services/report_service.py", "create"),
        ("sqlalchemy/orm/session.py", "flush"),
    ]
    assert not any("SENTINEL" in frame or "\n" in frame for frame in frames)


def test_frames_chained_traceback_contributes_only_its_first_traceback() -> None:
    frames = extract_frames(CHAINED_STACK)

    assert [frame_location(frame) for frame in frames] == [
        ("policyengine_api/services/cache.py", "read"),
    ]


def test_frames_explicitly_chained_traceback_contributes_only_its_cause() -> None:
    frames = extract_frames(chained_stack(recursion_depth=2))

    assert [frame_location(frame) for frame in frames] == [
        ("policyengine_api/services/household.py", "calculate"),
        ("policyengine_core/simulation.py", "calculate"),
        ("policyengine_core/simulation.py", "calculate"),
    ]


def test_frames_pattern_reads_exception_group_tracebacks() -> None:
    frames = extract_frames(EXCEPTION_GROUP_STACK)

    assert [frame_location(frame) for frame in frames] == [
        ("policyengine_simulation_gateway/app.py", "run"),
        ("policyengine_simulation_gateway/worker.py", "step"),
    ]


def test_frames_pattern_skips_a_frame_header_cut_off_by_truncation() -> None:
    cut_at = STANDARD_STACK.index("create_report") + len("create_re")
    frames = extract_frames(STANDARD_STACK[:cut_at])

    assert [frame_location(frame) for frame in frames] == [
        ("flask/app.py", "dispatch_request"),
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
def test_frames_paths_drop_installation_prefixes(path: str, normalized: str) -> None:
    assert normalize_path(path) == normalized


def test_frames_locations_ignore_line_numbers() -> None:
    first = frame_location('/app/policyengine_api/x.py", line 10, in handler')
    second = frame_location('/srv/policyengine_api/x.py", line 99, in handler')

    assert first == second == ("policyengine_api/x.py", "handler")


def test_frames_choose_the_three_innermost_application_frames() -> None:
    frames = [
        '/app/policyengine_api/routes/a.py", line 1, in outer',
        '/app/policyengine_api/services/b.py", line 2, in middle',
        '/app/policyengine_api/services/c.py", line 3, in inner',
        '/opt/venv/lib/python3.12/site-packages/sqlalchemy/orm/d.py", line 4, in lib',
        '/app/policyengine_api/services/e.py", line 5, in callback',
        '/venv/lib/python3.12/site-packages/sqlalchemy/orm/f.py", line 6, in raises',
    ]

    assert fingerprint_frames(frames) == ("middle", "inner", "callback")


def test_frames_count_simulation_and_stage12_packages_as_application_code() -> None:
    frames = [
        '/pkg/modal/_runtime.py", line 1, in run',
        '/root/policyengine_simulation_executor/run.py", line 2, in execute',
        '/root/policyengine_stage12_persistence/store.py", line 3, in save',
        '/pkg/synchronicity/combined_types.py", line 4, in __call__',
    ]

    assert fingerprint_frames(frames) == ("execute", "save")


def test_frames_are_keyed_by_function_name_without_leading_underscores() -> None:
    frames = [
        '/app/policyengine_api/services/regions.py", line 12, in _resolve_region',
        '/app/policyengine_api/services/regions.py", line 30, in __load_boundaries',
        '/app/policyengine_api/services/regions.py", line 44, in __getitem__',
    ]

    assert fingerprint_frames(frames) == (
        "resolve_region",
        "load_boundaries",
        "getitem__",
    )


def test_frames_without_application_frames_use_the_innermost_frames() -> None:
    frames = [
        '/usr/local/lib/python3.13/asyncio/a.py", line 1, in first',
        '/pkg/modal/b.py", line 2, in second',
        '/pkg/modal/c.py", line 3, in third',
        '/pkg/synchronicity/d.py", line 4, in fourth',
    ]

    assert fingerprint_frames(frames) == ("second", "third", "fourth")


@pytest.mark.parametrize("frames", [[], None, ["not a frame header"]])
def test_frames_without_a_stack_use_a_placeholder(frames: list[str] | None) -> None:
    assert fingerprint_frames(frames) == ("-",)


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
    value: str | None, expected: str
) -> None:
    assert public_error_type(value) == expected


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
    value: str | None, expected: str
) -> None:
    assert public_route(value) == expected


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
    value: str | None, expected: str
) -> None:
    assert public_family(value) == expected


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
    value: str | None, expected: str
) -> None:
    assert public_operation(value) == expected


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
    value: object, expected: int | None
) -> None:
    assert public_status(value) == expected
