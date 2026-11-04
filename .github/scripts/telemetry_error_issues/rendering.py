"""Issue titles and bodies: the measures table, the state and a Logs Explorer link."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from telemetry_error_issues.groups import completions_missing
from telemetry_error_issues.log_source import (
    LOCATION_PATTERN,
    LOG_BUCKET_PATTERN,
    LOG_VIEW_PATTERN,
    PROJECT_ID_PATTERN,
    checked_identifier,
)
from telemetry_error_issues.normalization import MISSING, UNRECOGNIZED
from telemetry_error_issues.records import FINGERPRINT_ALGORITHM
from telemetry_error_issues.window import REPORTING_TIME_ZONE, ReportingWindow

if TYPE_CHECKING:
    from telemetry_error_issues.groups import EnvironmentMeasures, ErrorGroup
    from telemetry_error_issues.log_source import LogSource

ISSUE_TITLE_PREFIX = "[telemetry]"
MAX_TITLE_LENGTH = 256
SECTION_START = "<!-- telemetry-error-issues:start -->"
SECTION_END = "<!-- telemetry-error-issues:end -->"
STATE_PATTERN = re.compile(r"<!-- telemetry-error-issues:state (\{[^\n]*?\}) -->")
NOT_AVAILABLE = "n/a"
LOGS_EXPLORER_URL = "https://console.cloud.google.com/logs/query"
SCHEMA_VERSION = "policyengine.observability.v2"
SIMULATION_FAMILY = "policyengine-simulation-py"


def code(value: str) -> str:
    """Return ``value`` as Markdown inline code."""
    return f"`{value}`"


def _place(group: ErrorGroup) -> str:
    """Describe where the group fails: its route, else its operation, else nothing."""
    if group.route != MISSING:
        return f" on {code(group.route)}"
    if group.kind == "message" and group.operation != MISSING:
        return f" in {code(group.operation)}"
    return ""


def _status_text(group: ErrorGroup) -> str:
    return "HTTP error" if group.status_code is None else f"HTTP {group.status_code}"


def _summary(group: ErrorGroup) -> str:
    if group.kind == "exception":
        return group.error_type
    if group.kind == "message":
        return "logged error"
    return f"{_status_text(group)} without recorded exception"


def issue_title(group: ErrorGroup) -> str:
    """Return the issue title, which names the fingerprint for matching.

    The route is left out when the title would exceed GitHub's length limit.
    """
    lead = f"{ISSUE_TITLE_PREFIX} {group.family}: {_summary(group)}"
    suffix = f" ({group.fingerprint})"
    title = f"{lead}{_place(group)}{suffix}"
    return title if len(title) <= MAX_TITLE_LENGTH else f"{lead}{suffix}"


def _logs_timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _logs_filters(group: ErrorGroup) -> list[str]:
    """Return logging query clauses that select the group's records."""
    filters = [f'jsonPayload.schema_version="{SCHEMA_VERSION}"']
    if group.family == SIMULATION_FAMILY:
        filters.append(
            f'jsonPayload."service.name"=~"^{SIMULATION_FAMILY}[0-9]+-[0-9]+-[0-9]+$"'
        )
    elif group.family not in {MISSING, UNRECOGNIZED}:
        filters.append(f'jsonPayload."service.name"="{group.family}"')
    if group.kind == "failed_request":
        filters.append('jsonPayload."event.name"="request.completed"')
    else:
        filters.append("severity>=ERROR")
    if group.kind == "exception" and group.error_type not in {MISSING, UNRECOGNIZED}:
        filters.append(f'jsonPayload."error.type"="{group.error_type}"')
    if group.kind != "exception" and group.route not in {MISSING, UNRECOGNIZED}:
        filters.append(f'jsonPayload."http.route"="{group.route}"')
    elif group.kind == "message" and group.operation not in {MISSING, UNRECOGNIZED}:
        filters.append(f'jsonPayload."operation.name"="{group.operation}"')
    if group.kind == "failed_request" and group.status_code is not None:
        filters.append(f'jsonPayload."http.response.status_code"={group.status_code}')
    return filters


def _log_view_path(log_source: LogSource) -> str:
    """Return the log view's resource name, once each part has passed its pattern."""
    project_id = checked_identifier(
        log_source.project_id, PROJECT_ID_PATTERN, "the project ID"
    )
    location = checked_identifier(
        log_source.bucket_location, LOCATION_PATTERN, "the log bucket location"
    )
    bucket = checked_identifier(log_source.bucket, LOG_BUCKET_PATTERN, "the log bucket")
    view = checked_identifier(log_source.view, LOG_VIEW_PATTERN, "the log view")
    return f"projects/{project_id}/locations/{location}/buckets/{bucket}/views/{view}"


def logs_explorer_url(
    group: ErrorGroup, window: ReportingWindow, log_source: LogSource
) -> str:
    """Return a Logs Explorer link to the group's records in the window."""
    query = "\n".join(
        [
            *_logs_filters(group),
            f'timestamp>="{_logs_timestamp(window.start)}"',
            f'timestamp<"{_logs_timestamp(window.end)}"',
        ]
    )
    view = _log_view_path(log_source)
    project_id = log_source.project_id
    settings = {"query": query, "storageScope": f"storage,{view}"}
    encoded = "".join(
        f";{name}={quote(value, safe='')}" for name, value in settings.items()
    )
    return f"{LOGS_EXPLORER_URL}{encoded}?{urlencode({'project': project_id})}"


def eastern_time(moment: datetime | None) -> str:
    """Return ``moment`` in US Eastern time, such as 2026-10-20 12:00 EDT, or n/a."""
    if moment is None:
        return NOT_AVAILABLE
    return moment.astimezone(REPORTING_TIME_ZONE).strftime("%Y-%m-%d %H:%M %Z")


def window_text(window: ReportingWindow) -> str:
    """Describe the window by its Eastern start and end, and its length in hours."""
    return (
        f"{eastern_time(window.start)} to {eastern_time(window.end)} "
        f"({window.hours:.0f} hours)"
    )


def _error_rate(measures: EnvironmentMeasures) -> str:
    """Return the error rate as a percentage with its counts, or n/a.

    When more requests failed than were logged as completed, a percentage
    would exceed 100%, so n/a is shown with the two counts instead.
    """
    if measures.error_rate is None:
        if completions_missing(
            measures.route_affected_requests, measures.route_requests
        ):
            return (
                f"{NOT_AVAILABLE} ({measures.route_affected_requests:,} affected "
                f"requests, only {measures.route_requests:,} logged as completed)"
            )
        return NOT_AVAILABLE
    return (
        f"{measures.error_rate:.2%} ({measures.route_affected_requests:,} of "
        f"{measures.route_requests:,} requests)"
    )


def _measures_table(group: ErrorGroup) -> list[str]:
    rows = [
        ("Occurrences", lambda measures: f"{measures.occurrences:,}"),
        ("Affected requests", lambda measures: f"{measures.affected_requests:,}"),
        ("Observability IDs", lambda measures: f"{measures.observability_ids:,}"),
        ("Error rate on affected routes", _error_rate),
        ("Occurrences per hour", lambda measures: f"{measures.hourly_rate:.2f}"),
        (
            "Occurrences per hour, previous 7 days",
            lambda measures: f"{measures.previous_hourly_rate:.2f}",
        ),
        (
            "First seen in the last 8 days",
            lambda measures: eastern_time(measures.first_seen),
        ),
        ("Last seen", lambda measures: eastern_time(measures.last_seen)),
    ]
    return [
        "| Measure | Production | Staging |",
        "| --- | --- | --- |",
        *(
            f"| {name} | {describe(group.production)} | {describe(group.staging)} |"
            for name, describe in rows
        ),
    ]


def _group_details(group: ErrorGroup) -> list[str]:
    details = [
        f"- Kind: {group.kind} (fingerprint algorithm {FINGERPRINT_ALGORITHM})",
        f"- Service: {code(group.family)}",
    ]
    if group.kind == "exception":
        details.append(f"- Exception type: {code(group.error_type)}")
    if group.kind == "failed_request":
        details.append(f"- Response: {_status_text(group)}")
    if group.kind == "message" and group.operation != MISSING:
        details.append(f"- Operation: {code(group.operation)}")
    details.append(f"- Most frequent route: {code(group.route)}")
    return details


def _state_comment(group: ErrorGroup, window: ReportingWindow) -> str:
    state = {
        "algorithm": FINGERPRINT_ALGORITHM,
        "fingerprint": group.fingerprint,
        "kind": group.kind,
        "window_end": window.end.astimezone(UTC).isoformat(),
    }
    return f"<!-- telemetry-error-issues:state {json.dumps(state, sort_keys=True)} -->"


def parse_state(body: str) -> dict[str, Any] | None:
    """Return the state the job last wrote into an issue body, if it is there."""
    match = STATE_PATTERN.search(body)
    if match is None:
        return None
    try:
        state = json.loads(match.group(1))
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def issue_section(
    group: ErrorGroup, window: ReportingWindow, log_source: LogSource
) -> str:
    """Return the marked section of the issue body, which each run replaces."""
    related = ", ".join(map(code, group.related_fingerprints))
    lines = [
        SECTION_START,
        f"### Error group {code(group.fingerprint)}",
        "",
        *_group_details(group),
        f"- Window: {window_text(window)}",
        "",
        *_measures_table(group),
        "",
        (
            f"Related fingerprints (sharing traces): {related}"
            if related
            else "Related fingerprints: none"
        ),
        "",
        (
            f"[Matching log records in Logs Explorer]"
            f"({logs_explorer_url(group, window, log_source)}), for the window only. "
            f"It needs read access to the `{log_source.project_id}` project."
        ),
        "",
        _state_comment(group, window),
        SECTION_END,
    ]
    return "\n".join(lines)


def issue_body(
    group: ErrorGroup, window: ReportingWindow, log_source: LogSource
) -> str:
    """Return a new issue's body: a short note, then the marked section."""
    note = (
        "The daily telemetry error report opened this issue for a production "
        "error group. Each run replaces the marked section below with the "
        "latest day's measures; text outside it is kept."
    )
    return f"{note}\n\n{issue_section(group, window, log_source)}\n"
