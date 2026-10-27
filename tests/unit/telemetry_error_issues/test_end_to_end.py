"""End-to-end tests of telemetry_error_issues.cli.main and its public output."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import unquote

import pytest
from telemetry_error_issues.cli import Runtime, main
from telemetry_error_issues.transport import HttpResponse

from tests.unit.telemetry_error_issues.bigquery_support import (
    ACCESS_TOKEN,
    FakeTransport,
    json_response,
    query_response,
    sent_parameters,
)
from tests.unit.telemetry_error_issues.github_support import REPOSITORY, FakeGitHub
from tests.unit.telemetry_error_issues.report_support import (
    APPLICATION_FRAMES,
    EASTERN,
    PROJECT_ID,
    WINDOW_NOON,
    hours_after_window_noon,
    sentinel_row,
)

if TYPE_CHECKING:
    from pathlib import Path

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
        error_rows: list[list[object]],
        count_rows: list[list[object]] = (),
    ) -> None:
        self.error_rows = error_rows
        self.count_rows = list(count_rows)
        self.requests: list[object] = []

    def __call__(self, request: object) -> object:
        self.requests.append(request)
        label = json.loads(request.body)["labels"]["query"]
        if label == "error-records":
            response = query_response(ERROR_RECORD_FIELDS, self.error_rows)
        else:
            response = query_response(REQUEST_COUNT_FIELDS, self.count_rows)
        return json_response(response)

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
    tmp_path: Path,
    bigquery: object,
    github: FakeGitHub,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    runtime = Runtime(
        environ=_environment(tmp_path) if environment is None else environment,
        bigquery_transport=bigquery,
        github_transport=github,
        now=lambda: SCHEDULED_RUN_TIME,
        sleep=github.sleep,
        clock=github.clock,
        stdout=stdout,
        stderr=stderr,
    )
    exit_code = main(["--project-id", PROJECT_ID, *arguments], runtime=runtime)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _three_failures(**overrides: object) -> list[list[object]]:
    return [
        _error_row(
            request_key=f"r{index}",
            timestamp=_microseconds(hours_after_window_noon(index)),
            **overrides,
        )
        for index in range(3)
    ]


def test_main_queries_groups_and_opens_issues_for_the_previous_day(
    tmp_path: Path,
) -> None:
    bigquery = FakeBigQuery(
        _three_failures(),
        [["policyengine-api", "production", "/<country_id>/report", "600"]],
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
    window_end = sent_parameters(bigquery)["window_end"]["parameterValue"]
    assert window_end["value"] == "2026-10-21 04:00:00+00:00"
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
    window_end = sent_parameters(bigquery)["window_end"]["parameterValue"]
    assert window_end["value"] == "2026-10-16 04:00:00+00:00"
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


def test_main_reports_an_api_failure_by_stage_class_and_status_only(
    tmp_path: Path,
) -> None:
    error_body = {
        "error": {
            "message": "SENTINEL echoed value",
            "errors": [{"reason": "backendError", "message": "SENTINEL"}],
        }
    }
    failing = FakeTransport(
        [json_response(error_body, status=500, reason="SENTINEL")],
    )

    exit_code, stdout, stderr = _run_main(tmp_path, failing, FakeGitHub())

    assert exit_code == 1
    assert stdout == ""
    assert stderr == (
        "query error records failed: BigQueryError (HTTP 500 backendError)\n"
    )


def test_main_reports_an_unexpected_exception_by_class_only(tmp_path: Path) -> None:
    def broken_transport(request: object) -> object:
        message = "SENTINEL connection detail"
        raise RuntimeError(message)

    exit_code, _, stderr = _run_main(tmp_path, broken_transport, FakeGitHub())

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
    sentinel_values["stack_truncated"] = "true"
    sentinel_values["frames"] = ['/app/SENTINEL.py", line 1, in SENTINEL']
    rows = [
        _error_row(
            **{
                **sentinel_values,
                "request_key": f"SENTINEL request {index}",
                "timestamp": _microseconds(hours_after_window_noon(index)),
            }
        )
        for index in range(3)
    ]
    count_rows = [["SENTINEL service", "production", "SENTINEL route", "10"]]
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
