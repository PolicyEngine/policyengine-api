"""End-to-end tests of telemetry_error_issues.cli.main and its public output."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import unquote

import pytest
from google.api_core.exceptions import BadRequest, Forbidden, InternalServerError
from telemetry_error_issues.cli import Runtime, main
from telemetry_error_issues.transport import HttpResponse

from tests.unit.telemetry_error_issues.bigquery_support import (
    ACCESS_TOKEN,
    FakeBigQueryClient,
    sent_parameters,
)
from tests.unit.telemetry_error_issues.github_support import REPOSITORY, FakeGitHub
from tests.unit.telemetry_error_issues.report_support import (
    APPLICATION_FRAMES,
    EASTERN,
    LOG_SOURCE_ENVIRONMENT,
    PROJECT_ID,
    WINDOW_NOON,
    hours_after_window_noon,
    input_orders,
    sentinel_row,
)

if TYPE_CHECKING:
    from pathlib import Path

ERROR_RECORD_COLUMNS = (
    "timestamp",
    "service_name",
    "environment_name",
    "event_name",
    "error_type",
    "error_handled",
    "frames",
    "stack_truncated",
    "message_template",
    "attribute_error_type",
    "failure_category",
    "route",
    "status_code",
    "operation_name",
    "request_key",
    "observability_key",
    "trace_key",
)
REQUEST_COUNT_COLUMNS = ("service_name", "environment_name", "route", "requests")
SCHEDULED_RUN_TIME = datetime(2026, 10, 21, 0, 45, tzinfo=EASTERN)


def _error_row(**overrides: object) -> dict[str, object]:
    """Return an error-record row with the types the client library gives it."""
    values: dict[str, object] = {
        "timestamp": WINDOW_NOON,
        "service_name": "policyengine-api",
        "environment_name": "production",
        "event_name": "exception.recorded",
        "error_type": "StaleDataError",
        "error_handled": "false",
        "frames": list(APPLICATION_FRAMES),
        "stack_truncated": False,
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
    return {column: values[column] for column in ERROR_RECORD_COLUMNS}


class FakeBigQuery(FakeBigQueryClient):
    """Answers the error-record and request-count queries with fixed rows."""

    def __init__(
        self,
        error_rows: list[dict[str, object]],
        count_rows: list[list[object]] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        super().__init__(
            {
                "error-records": error_rows,
                "request-counts": [
                    dict(zip(REQUEST_COUNT_COLUMNS, row, strict=True))
                    for row in count_rows
                ],
            },
            error=error,
        )


def _environment(tmp_path: Path, **overrides: str) -> dict[str, str]:
    environment = {
        "GOOGLE_OAUTH_ACCESS_TOKEN": ACCESS_TOKEN,
        "GITHUB_TOKEN": "fake-github-token",
        "GITHUB_REPOSITORY": REPOSITORY,
        "TELEMETRY_ERROR_FINGERPRINT_KEY": "f" * 64,
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        **LOG_SOURCE_ENVIRONMENT,
    }
    environment.update(overrides)
    return {name: value for name, value in environment.items() if value}


def _run_main(
    tmp_path: Path,
    bigquery: object,
    github: FakeGitHub,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    runtime = Runtime(
        environ=_environment(tmp_path) if environment is None else environment,
        bigquery_client_factory=bigquery.factory,
        github_transport=github,
        now=lambda: SCHEDULED_RUN_TIME,
        sleep=github.sleep,
        clock=github.clock,
        stdout=stdout,
        stderr=stderr,
    )
    exit_code = main(["--project-id", PROJECT_ID, *arguments], runtime=runtime)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _three_failures(**overrides: object) -> list[dict[str, object]]:
    return [
        _error_row(
            request_key=f"r{index}",
            timestamp=hours_after_window_noon(index),
            **overrides,
        )
        for index in range(3)
    ]


def test_main_queries_groups_and_opens_issues_for_the_previous_day(
    tmp_path: Path,
) -> None:
    bigquery = FakeBigQuery(
        _three_failures(),
        [["policyengine-api", "production", "/<country_id>/report", 600]],
    )
    github = FakeGitHub()

    exit_code, stdout, stderr = _run_main(tmp_path, bigquery, github)

    assert exit_code == 0, stderr
    issue = github.issues[1]
    assert "StaleDataError" in issue["title"]
    assert (
        "| Error rate on affected routes | 0.50% (3 of 600 requests) | n/a |"
        in (issue["body"])
    )
    window_end = sent_parameters(bigquery)["window_end"]
    assert window_end.value == datetime(2026, 10, 21, 4, 0, tzinfo=UTC)
    summary = (tmp_path / "summary.md").read_text()
    fingerprint = issue["title"].rsplit("(", 1)[1].rstrip(")")
    assert (
        f"| `{fingerprint}` | exception | `policyengine-api` | 3 | 0 | #1 | created |"
        in summary
    )
    assert summary in stdout


def test_main_dry_run_reports_actions_without_writing(tmp_path: Path) -> None:
    github = FakeGitHub()

    exit_code, stdout, _ = _run_main(
        tmp_path,
        FakeBigQuery(_three_failures()),
        github,
        "--dry-run",
    )

    assert exit_code == 0
    assert github.writes == []
    assert "Dry run: no issues were changed." in stdout
    assert "| - | created |" in stdout


def test_main_reports_the_requested_day(tmp_path: Path) -> None:
    bigquery = FakeBigQuery([])

    exit_code, stdout, _ = _run_main(
        tmp_path,
        bigquery,
        FakeGitHub(),
        "--report-date",
        "2026-10-15",
    )

    assert exit_code == 0
    window_end = sent_parameters(bigquery)["window_end"]
    assert window_end.value == datetime(2026, 10, 16, 4, 0, tzinfo=UTC)
    assert "## Telemetry error issues for 2026-10-15" in stdout
    assert "No error groups had failures in the window." in stdout


def test_main_rejects_a_day_that_has_not_ended(tmp_path: Path) -> None:
    exit_code, stdout, stderr = _run_main(
        tmp_path,
        FakeBigQuery([]),
        FakeGitHub(),
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
    tmp_path: Path,
) -> None:
    environment = _environment(
        tmp_path, GITHUB_TOKEN="", TELEMETRY_ERROR_FINGERPRINT_KEY=""
    )

    exit_code, _, stderr = _run_main(
        tmp_path,
        FakeBigQuery([]),
        FakeGitHub(),
        environment=environment,
    )

    assert exit_code == 1
    assert stderr == (
        "configuration failed: ConfigurationError (missing environment variables: "
        "GITHUB_TOKEN, TELEMETRY_ERROR_FINGERPRINT_KEY)\n"
    )


def test_main_rejects_a_short_fingerprint_key_without_printing_it(
    tmp_path: Path,
) -> None:
    environment = _environment(
        tmp_path, TELEMETRY_ERROR_FINGERPRINT_KEY="SENTINEL-short-key"
    )

    exit_code, stdout, stderr = _run_main(
        tmp_path,
        FakeBigQuery([]),
        FakeGitHub(),
        environment=environment,
    )

    assert exit_code == 1
    assert "at least 32 characters" in stderr
    assert "SENTINEL" not in stdout + stderr


def test_main_names_missing_log_settings(tmp_path: Path) -> None:
    environment = _environment(tmp_path, **dict.fromkeys(LOG_SOURCE_ENVIRONMENT, ""))

    exit_code, _, stderr = _run_main(
        tmp_path, FakeBigQuery([]), FakeGitHub(), environment=environment
    )

    assert exit_code == 1
    assert stderr == (
        "configuration failed: ConfigurationError (missing environment variables: "
        f"{', '.join(LOG_SOURCE_ENVIRONMENT)})\n"
    )


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("OBSERVABILITY_LOG_BUCKET", "SENTINEL bucket"),
        ("OBSERVABILITY_LOG_BUCKET_LOCATION", "SENTINEL/location"),
        ("OBSERVABILITY_LOG_DATASET", "SENTINEL`; DROP TABLE logs"),
        ("OBSERVABILITY_LOG_VIEW", "_AllLogs` WHERE SENTINEL"),
    ],
)
def test_main_refuses_a_log_name_that_is_not_an_identifier(
    tmp_path: Path, setting: str, value: str
) -> None:
    bigquery = FakeBigQuery([])

    exit_code, stdout, stderr = _run_main(
        tmp_path,
        bigquery,
        FakeGitHub(),
        environment=_environment(tmp_path, **{setting: value}),
    )

    assert exit_code == 1
    assert stdout == ""
    assert stderr == (
        f"configuration failed: ConfigurationError ({setting} is not a valid name)\n"
    )
    assert bigquery.queries == []


def test_main_refuses_a_project_id_that_is_not_an_identifier(tmp_path: Path) -> None:
    bigquery = FakeBigQuery([])

    exit_code, _, stderr = _run_main(
        tmp_path, bigquery, FakeGitHub(), "--project-id", "SENTINEL project"
    )

    assert exit_code == 1
    assert stderr == (
        "configuration failed: ConfigurationError (--project-id is not a valid name)\n"
    )
    assert bigquery.queries == []


def test_main_reports_an_api_failure_by_stage_class_and_status_only(
    tmp_path: Path,
) -> None:
    error = InternalServerError(
        "SENTINEL echoed value",
        errors=[{"reason": "backendError", "message": "SENTINEL"}],
    )
    failing = FakeBigQuery([], error=error)

    exit_code, stdout, stderr = _run_main(tmp_path, failing, FakeGitHub())

    assert exit_code == 1
    assert stdout == ""
    assert stderr == (
        "query error records failed: BigQueryError (HTTP 500 backendError)\n"
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            BadRequest(
                "SENTINEL message about the query",
                errors=[{"reason": "invalidQuery", "message": "SENTINEL detail"}],
            ),
            "query error records failed: BigQueryError (HTTP 400 invalidQuery)\n",
        ),
        (
            Forbidden(
                "SENTINEL access denied", errors=[{"reason": "SENTINEL: 'value'"}]
            ),
            "query error records failed: BigQueryError (HTTP 403 Forbidden)\n",
        ),
    ],
)
def test_main_never_prints_a_client_library_error_message(
    tmp_path: Path, error: Exception, expected: str
) -> None:
    # The library adds the query text to a failed job's error.
    error.debug_message = "SENTINEL query text"
    bigquery = FakeBigQuery(_three_failures(), error=error)

    exit_code, stdout, stderr = _run_main(tmp_path, bigquery, FakeGitHub())

    assert exit_code == 1
    assert stdout == ""
    assert stderr == expected
    assert not (tmp_path / "summary.md").exists()


def test_main_reports_an_unexpected_exception_by_class_only(tmp_path: Path) -> None:
    broken = FakeBigQuery([], error=RuntimeError("SENTINEL connection detail"))

    exit_code, _, stderr = _run_main(tmp_path, broken, FakeGitHub())

    assert exit_code == 1
    assert stderr == "query error records failed: RuntimeError\n"


def test_main_reports_a_github_failure_by_stage(tmp_path: Path) -> None:
    github = FakeGitHub()
    github.failures = [
        HttpResponse(
            status=403, reason="Forbidden", headers={}, body=b'{"message": "SENTINEL"}'
        )
    ]

    exit_code, _, stderr = _run_main(tmp_path, FakeBigQuery(_three_failures()), github)

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
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    sentinel_values = {
        name: value
        for name, value in sentinel_row(**overrides).items()
        if name not in {"timestamp", "environment_name", "frames", "stack_truncated"}
    }
    sentinel_values["stack_truncated"] = True
    sentinel_values["frames"] = ['/app/SENTINEL.py", line 1, in SENTINEL']
    rows = [
        _error_row(
            **{
                **sentinel_values,
                "request_key": f"SENTINEL request {index}",
                "timestamp": hours_after_window_noon(index),
            }
        )
        for index in range(3)
    ]
    count_rows = [["SENTINEL service", "production", "SENTINEL route", 10]]
    github = FakeGitHub()

    exit_code, stdout, stderr = _run_main(
        tmp_path, FakeBigQuery(rows, count_rows), github
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


def _requests_failing_with(error_type: str, count: int) -> list[dict[str, object]]:
    return [
        _error_row(
            error_type=error_type,
            request_key=f"{error_type}-{index}",
            timestamp=hours_after_window_noon(index + 1),
        )
        for index in range(count)
    ]


def _rows_that_tie() -> list[dict[str, object]]:
    """Return error rows that tie on everything the report orders records by.

    StaleDataError and TimeoutError each fail in two requests, and a third
    request logs both at the same moment, so whichever group it joins reaches
    the issue thresholds. Five groups then have three production failures and
    KeyError has four, so one group waits for a later run. KeyError fails
    twice on each of two routes, and one message group is logged by two
    operations at the same moment.
    """
    return [
        *_requests_failing_with("StaleDataError", 2),
        *_requests_failing_with("TimeoutError", 2),
        *(
            _error_row(error_type=error_type, request_key="both")
            for error_type in ("StaleDataError", "TimeoutError")
        ),
        *_requests_failing_with("ValueError", 3),
        *_requests_failing_with("TypeError", 3),
        *_requests_failing_with("LookupError", 3),
        *(
            _error_row(error_type="KeyError", request_key=f"route-{index}", route=route)
            for index, route in enumerate(
                ["/<country_id>/report", "/<country_id>/calculate"] * 2
            )
        ),
        *(
            _error_row(
                event_name=None,
                error_type=None,
                error_handled=None,
                frames=[],
                status_code=None,
                message_template="failed to save",
                request_key=f"operation-{index}",
                operation_name=operation,
            )
            for index, operation in enumerate(
                ("save_report", "save_policy", "save_policy")
            )
        ),
    ]


def test_main_publishes_the_same_report_in_any_row_order(tmp_path: Path) -> None:
    count_rows = [
        ["policyengine-api", "production", "/<country_id>/report", 600],
        ["policyengine-api", "production", "/<country_id>/calculate", 300],
    ]
    count_rows_by_order = input_orders(count_rows)
    published_by_order: dict[str, tuple[str, str, dict]] = {}

    for order, rows in input_orders(_rows_that_tie()).items():
        run_directory = tmp_path / order
        run_directory.mkdir()
        github = FakeGitHub()
        bigquery = FakeBigQuery(rows, count_rows_by_order[order])
        exit_code, stdout, stderr = _run_main(run_directory, bigquery, github)
        assert exit_code == 0, stderr
        summary = (run_directory / "summary.md").read_text()
        published_by_order[order] = (stdout, summary, github.issues)

    forward_summary = published_by_order["forward"][1]
    assert "7 error groups: 1 below-threshold, 5 created, 1 deferred." in (
        forward_summary
    )
    assert published_by_order["reversed"] == published_by_order["forward"]
    assert published_by_order["shuffled"] == published_by_order["forward"]
