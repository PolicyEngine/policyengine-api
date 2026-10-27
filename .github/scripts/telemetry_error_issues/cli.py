"""Report each day's telemetry error groups as GitHub issues.

The command line: it parses the arguments, reads the settings from the
environment, runs each stage of the report and writes the job summary.
``parse_arguments`` uses the first line of this docstring as the description
that ``--help`` prints.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, TypeVar

from telemetry_error_issues.bigquery import (
    BigQueryClient,
    fetch_error_records,
    fetch_request_counts,
    library_client,
)
from telemetry_error_issues.github_client import GitHubClient
from telemetry_error_issues.groups import build_groups
from telemetry_error_issues.log_source import (
    DATASET_PATTERN,
    LOCATION_PATTERN,
    LOG_BUCKET_PATTERN,
    LOG_VIEW_PATTERN,
    PROJECT_ID_PATTERN,
    LogSource,
    checked_identifier,
)
from telemetry_error_issues.normalization import MISSING
from telemetry_error_issues.records import fingerprint_key
from telemetry_error_issues.rendering import code, window_text
from telemetry_error_issues.sync import SyncResult, sync_issues
from telemetry_error_issues.transport import (
    ApiError,
    HttpRequest,
    HttpResponse,
    urllib_transport,
)
from telemetry_error_issues.window import (
    ReportingWindow,
    default_report_date,
    reporting_window,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import TextIO

    from google.cloud import bigquery

StageResult = TypeVar("StageResult")

# The repository variables that name the logs the run reads, each with the
# pattern its value must match. They say where the logs are; none of them
# changes how failures are grouped.
LOG_NAME_VARIABLES = {
    "OBSERVABILITY_LOG_BUCKET": LOG_BUCKET_PATTERN,
    "OBSERVABILITY_LOG_BUCKET_LOCATION": LOCATION_PATTERN,
    "OBSERVABILITY_LOG_DATASET": DATASET_PATTERN,
    "OBSERVABILITY_LOG_VIEW": LOG_VIEW_PATTERN,
}
REQUIRED_ENVIRONMENT_VARIABLES = (
    "GOOGLE_OAUTH_ACCESS_TOKEN",
    "GITHUB_TOKEN",
    "GITHUB_REPOSITORY",
    "TELEMETRY_ERROR_FINGERPRINT_KEY",
    *LOG_NAME_VARIABLES,
    "OBSERVABILITY_SERVICE_NAMESPACE",
)
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _report_date_argument(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        msg = "expected an Eastern calendar date as YYYY-MM-DD"
        raise argparse.ArgumentTypeError(msg) from error


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line; argparse exits with code 2 on invalid input."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--project-id",
        required=True,
        help="Google Cloud project that holds the linked BigQuery dataset",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="query and group errors, but make no changes to GitHub issues",
    )
    parser.add_argument(
        "--report-date",
        type=_report_date_argument,
        default=None,
        help="Eastern calendar day to report (default: the previous day)",
    )
    return parser.parse_args(argv)


class ConfigurationError(Exception):
    """The run's settings are missing or invalid. The text names only settings."""


class StageFailedError(Exception):
    """A stage of the run failed.

    The text holds only the stage, the exception class, and for an API error
    the HTTP status and reason, so it can be printed in a public log.
    """


def _current_time() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Runtime:
    """What a run reads from outside the process, so tests can replace it."""

    environ: Mapping[str, str]
    stdout: TextIO
    stderr: TextIO
    bigquery_client_factory: Callable[[str, str], bigquery.Client] = library_client
    github_transport: Callable[[HttpRequest], HttpResponse] = urllib_transport
    now: Callable[[], datetime] = _current_time
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def from_process(cls) -> Runtime:
        """Use the process environment, standard streams and the network."""
        return cls(environ=os.environ, stdout=sys.stdout, stderr=sys.stderr)


class Settings(NamedTuple):
    """Settings read from the environment; none of them is ever printed."""

    google_access_token: str
    github_credential: str
    repository: str
    fingerprint_key: bytes
    log_source: LogSource
    summary_path: str | None


def read_settings(environ: Mapping[str, str], project_id: str) -> Settings:
    """Read and check the environment variables the run needs, and its project."""
    missing = [name for name in REQUIRED_ENVIRONMENT_VARIABLES if not environ.get(name)]
    if missing:
        msg = f"missing environment variables: {', '.join(missing)}"
        raise ConfigurationError(msg)
    if not REPOSITORY_PATTERN.match(environ["GITHUB_REPOSITORY"]):
        msg = "GITHUB_REPOSITORY must be owner/name"
        raise ConfigurationError(msg)
    try:
        key = fingerprint_key(environ["TELEMETRY_ERROR_FINGERPRINT_KEY"])
        checked_identifier(project_id, PROJECT_ID_PATTERN, "--project-id")
        for name, pattern in LOG_NAME_VARIABLES.items():
            checked_identifier(environ[name], pattern, name)
    except ValueError as error:
        raise ConfigurationError(str(error)) from None
    log_source = LogSource(
        project_id=project_id,
        bucket=environ["OBSERVABILITY_LOG_BUCKET"],
        bucket_location=environ["OBSERVABILITY_LOG_BUCKET_LOCATION"],
        dataset=environ["OBSERVABILITY_LOG_DATASET"],
        view=environ["OBSERVABILITY_LOG_VIEW"],
        service_namespace=environ["OBSERVABILITY_SERVICE_NAMESPACE"],
    )
    return Settings(
        google_access_token=environ["GOOGLE_OAUTH_ACCESS_TOKEN"],
        github_credential=environ["GITHUB_TOKEN"],
        repository=environ["GITHUB_REPOSITORY"],
        fingerprint_key=key,
        log_source=log_source,
        summary_path=environ.get("GITHUB_STEP_SUMMARY") or None,
    )


def _report_window(report_date: date | None, now: datetime) -> ReportingWindow:
    window = reporting_window(report_date or default_report_date(now))
    if window.end > now:
        msg = f"{window.start.date().isoformat()} has not ended in US Eastern time"
        raise ConfigurationError(msg)
    return window


def _failure_description(stage: str, error: Exception) -> str:
    detail = ""
    if isinstance(error, ConfigurationError):
        detail = f" ({error})"
    elif isinstance(error, ApiError) and error.status is not None:
        detail = f" (HTTP {error.status} {error.reason})"
    return f"{stage} failed: {type(error).__name__}{detail}"


def _stage(name: str, operation: Callable[[], StageResult]) -> StageResult:
    """Run one stage, replacing any failure with a description safe to print."""
    try:
        return operation()
    except Exception as error:
        raise StageFailedError(_failure_description(name, error)) from error


def render_summary(
    result: SyncResult, window: ReportingWindow, *, dry_run: bool
) -> str:
    """Return the job summary: fingerprints, counts, issue numbers and actions."""
    lines = [
        f"## Telemetry error issues for {window.start.date().isoformat()}",
        "",
        f"Window: {window_text(window)}.",
    ]
    if dry_run:
        lines.append("Dry run: no issues were changed.")
    if not result.actions:
        lines += ["", "No error groups had failures in the window."]
        return "\n".join(lines)
    totals = Counter(action.action for action in result.actions)
    described = ", ".join(f"{count} {name}" for name, count in sorted(totals.items()))
    lines += [
        "",
        f"{len(result.actions)} error groups: {described}.",
        "",
        "| Fingerprint | Kind | Service | Production | Staging | Issue | Action |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for action in result.actions:
        issue = MISSING if action.issue_number is None else f"#{action.issue_number}"
        lines.append(
            f"| {code(action.fingerprint)} | {action.kind} | {code(action.family)} "
            f"| {action.production_occurrences:,} | {action.staging_occurrences:,} "
            f"| {issue} | {action.action} |"
        )
    return "\n".join(lines)


def _append_summary(path: str, summary: str) -> None:
    with Path(path).open("a", encoding="utf-8") as summary_file:
        summary_file.write(f"{summary}\n")


def _report(arguments: argparse.Namespace, runtime: Runtime) -> str:
    settings = _stage(
        "configuration", lambda: read_settings(runtime.environ, arguments.project_id)
    )
    window = _stage(
        "configuration", lambda: _report_window(arguments.report_date, runtime.now())
    )
    bigquery_client = _stage(
        "configuration",
        lambda: BigQueryClient(
            settings.log_source,
            settings.google_access_token,
            runtime.bigquery_client_factory,
        ),
    )
    records = _stage(
        "query error records", lambda: fetch_error_records(bigquery_client, window)
    )
    request_counts = _stage(
        "query request counts", lambda: fetch_request_counts(bigquery_client, window)
    )
    groups = _stage(
        "group errors",
        lambda: build_groups(records, request_counts, window, settings.fingerprint_key),
    )
    github = GitHubClient(
        settings.repository,
        settings.github_credential,
        runtime.github_transport,
        sleep=runtime.sleep,
        clock=runtime.clock,
    )
    result = _stage(
        "sync issues",
        lambda: sync_issues(
            groups, window, settings.log_source, github, dry_run=arguments.dry_run
        ),
    )
    summary = render_summary(result, window, dry_run=arguments.dry_run)
    summary_path = settings.summary_path
    if summary_path:
        _stage("write job summary", lambda: _append_summary(summary_path, summary))
    return summary


def main(argv: list[str] | None = None, runtime: Runtime | None = None) -> int:
    """Run one report and return the process exit code.

    A failed stage prints one line naming the stage and exception class, never
    the exception's message, and returns 1.
    """
    arguments = parse_arguments(argv)
    runtime = runtime or Runtime.from_process()
    try:
        summary = _report(arguments, runtime)
    except StageFailedError as failure:
        print(failure, file=runtime.stderr)
        return 1
    print(summary, file=runtime.stdout)
    return 0
