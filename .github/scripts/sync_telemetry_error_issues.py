"""Report each day's telemetry error groups as GitHub issues.

Each run reads one US Eastern calendar day of error records from the central
Cloud Logging bucket through its linked BigQuery dataset. It groups the records
by a keyed fingerprint, measures each group in production and staging, and
creates or updates one GitHub issue per production error group.

Workflow logs, job summaries and issues in this repository are public. The
script therefore publishes only fingerprints, counts, code-defined names and a
Logs Explorer link, never error messages, stack text or identifiers.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as time_of_day
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from typing import TextIO

StageResult = TypeVar("StageResult")

REPORTING_TIME_ZONE = ZoneInfo("America/New_York")
MIDNIGHT = time_of_day(0, 0)

# Shown in place of a value that is missing, or that fails validation and so
# might not be code-defined.
MISSING = "-"
UNRECOGNIZED = "<unrecognized>"

PRODUCTION_ENVIRONMENT_NAMES = frozenset({"production", "main"})
STAGING_ENVIRONMENT_NAMES = frozenset({"staging"})
VERSIONED_SIMULATION_SERVICE = re.compile(r"^(policyengine-simulation-py)\d+-\d+-\d+$")

# Captures 'path", line N, in function' from each frame header of a Python
# traceback, including indented and "|"-prefixed exception group frames. It has
# one capturing group because BigQuery's REGEXP_EXTRACT_ALL allows only one,
# and the trailing newline skips a header that stack truncation cut short.
FRAME_PATTERN = r'File "([^"\n]+", line [0-9]+, in [^\s]+)\n'
# Matches everything after the first traceback of a chained exception, so the
# query can remove it before extracting frames. The logging library keeps only
# the start of a long stack, which can drop the final traceback; the first
# traceback is always kept, so frames from it give an exception the same
# fingerprint however long its stack is.
CHAINED_EXCEPTION_PATTERN = (
    r"(?s)\n\n(?:The above exception was the direct cause of the following "
    r"exception|During handling of the above exception, another exception "
    r"occurred):\n.*"
)
FRAME_PARTS = re.compile(r'^(?P<path>[^"\n]+)", line [0-9]+, in (?P<function>\S+)$')
FINGERPRINT_FRAME_COUNT = 3
# A message's template is its first three whole words after removing quoted
# values, so values don't split one error into many groups. A single quote
# opens a value only after the start of the message or a character that is not
# a letter or digit; otherwise it is an apostrophe, as in "can't" or "users'".
# The query passes these to REGEXP_REPLACE and REGEXP_EXTRACT_ALL.
DOUBLE_QUOTED_PATTERN = r'"[^"]*"'
SINGLE_QUOTED_PATTERN = r"(^|[^A-Za-z0-9])'[^']*'"
TEMPLATE_WORD_PATTERN = r"\b[A-Za-z]+\b"
INSTALLED_PACKAGE_PREFIX = re.compile(r"^.*/(?:site|dist)-packages/")
STANDARD_LIBRARY_PREFIX = re.compile(r"^.*/lib/python3(?:\.\d+)?/")
APPLICATION_PACKAGES = (
    r"(?:policyengine_api|policyengine_fastapi"
    r"|policyengine_simulation_[a-z0-9_]+|policyengine_stage12_[a-z0-9_]+)/"
)
APPLICATION_PATH = re.compile(rf"^{APPLICATION_PACKAGES}")
APPLICATION_PATH_IN_ABSOLUTE_PATH = re.compile(rf"(?:^|/)({APPLICATION_PACKAGES}.*)$")
FALLBACK_PATH_COMPONENTS = 2

ERROR_TYPE_PATTERN = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$", re.ASCII)
MAX_ERROR_TYPE_LENGTH = 120
UNMATCHED_ROUTE = "<unmatched>"
MAX_ROUTE_LENGTH = 200
ROUTE_PARAMETER = re.compile(
    r"^(?:<(?:[a-z]+:)?[A-Za-z_]\w*>|\{[A-Za-z_]\w*(?::[a-z]+)?\})$", re.ASCII
)
ROUTE_LITERAL = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,39}$")
# Literal route segments are words such as "v2" or "user-policies". A segment
# with more digits than this is more likely a record ID than code.
MAX_ROUTE_LITERAL_DIGITS = 2
FAMILY_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
MAX_FAMILY_LENGTH = 63
OPERATION_PATTERN = re.compile(r"^[A-Za-z_][\w.:/-]*$", re.ASCII)
MAX_OPERATION_LENGTH = 100
LOWEST_HTTP_STATUS = 100
HIGHEST_HTTP_STATUS = 599

REQUEST_COMPLETED_EVENT = "request.completed"
# Changing how fingerprints are computed changes every fingerprint, and the
# job matches existing issues only by the current algorithm. A change to it
# must say how existing issues are carried over.
FINGERPRINT_ALGORITHM = 1
FINGERPRINT_LENGTH = 16
MIN_FINGERPRINT_KEY_LENGTH = 32

# Each run also reads the seven days before the window, for comparison rates,
# first-seen times and regressions.
LOOKBACK = timedelta(days=7)
REPORTED_ENVIRONMENTS = ("production", "staging")
MAX_RELATED_FINGERPRINTS = 3

HTTP_TIMEOUT_SECONDS = 60
# A short code from an API error, such as "invalidQuery" or "Not Found". The
# error's message is never used, because it can repeat values from a record.
ERROR_REASON_PATTERN = re.compile(r"^[A-Za-z][A-Za-z ]{0,59}$")

BIGQUERY_API = "https://bigquery.googleapis.com/bigquery/v2"
LINKED_DATASET = "observability_logs"
MAXIMUM_BYTES_BILLED = 5 * 1024**3
QUERY_WAIT_MILLISECONDS = 30_000
MAX_QUERY_POLLS = 40
UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ISSUE_TITLE_PREFIX = "[telemetry]"
MAX_TITLE_LENGTH = 256
SECTION_START = "<!-- telemetry-error-issues:start -->"
SECTION_END = "<!-- telemetry-error-issues:end -->"
STATE_PATTERN = re.compile(r"<!-- telemetry-error-issues:state (\{[^\n]*?\}) -->")
NOT_AVAILABLE = "n/a"
LOGS_EXPLORER_URL = "https://console.cloud.google.com/logs/query"
LOG_BUCKET = "policyengine-observability"
LOG_VIEW = "_AllLogs"
SCHEMA_VERSION = "policyengine.observability.v2"
SIMULATION_FAMILY = "policyengine-simulation-py"
GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_PAGE_SIZE = 100
BOT_LOGIN = "github-actions[bot]"
TITLE_FINGERPRINT = re.compile(r"\(([0-9a-f]{16})\)$")
BASE_LABEL = "telemetry-error"
REGRESSION_LABEL = "regression"
SERVICE_LABEL_PREFIX = "service: "
MAX_LABEL_LENGTH = 50
LABEL_DETAILS = {
    BASE_LABEL: ("b60205", "Opened by the daily telemetry error report"),
    REGRESSION_LABEL: ("d93f0b", "An error that returned after its issue was closed"),
}
SERVICE_LABEL_DETAILS = ("1d76db", "Service that produced a telemetry error group")
# A production group opens an issue only when it fails this often, in this many
# distinct requests, during the window; the same thresholds reopen an issue.
MIN_PRODUCTION_OCCURRENCES = 3
MIN_PRODUCTION_REQUESTS = 2
MAX_NEW_ISSUES_PER_RUN = 5
# Failures in the first day after an issue is closed may come from code that
# hasn't been deployed yet, so they never reopen it.
REOPEN_DELAY = timedelta(hours=24)
REOPENABLE_CLOSE_REASONS = frozenset({None, "completed"})
# GitHub asks clients to send content-creating requests one at a time, at
# least a second apart, and to wait as its rate-limit responses say.
MIN_SECONDS_BETWEEN_WRITES = 1.0
MAX_RATE_LIMIT_RETRIES = 3
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60
MAX_RATE_LIMIT_WAIT_SECONDS = 300
RATE_LIMIT_STATUSES = frozenset({HTTPStatus.FORBIDDEN, HTTPStatus.TOO_MANY_REQUESTS})
REQUIRED_ENVIRONMENT_VARIABLES = (
    "GOOGLE_OAUTH_ACCESS_TOKEN",
    "GITHUB_TOKEN",
    "GITHUB_REPOSITORY",
    "TELEMETRY_ERROR_FINGERPRINT_KEY",
)
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
HEALTH_CHECK_ROUTES = (
    "/health",
    "/simulation-gateway-check",
    "/liveness-check",
    "/readiness-check",
)

# Each query reads the linked dataset's _AllLogs view. Only code-defined or
# normalized values leave BigQuery: stacks only as frame headers, messages
# only as templates (see DOUBLE_QUOTED_PATTERN), and identifiers only as
# SHA-256 hashes. Duplicate deliveries of one log entry are removed.
ERROR_RECORDS_QUERY = r"""
SELECT
  timestamp,
  JSON_VALUE(json_payload, '$."service.name"') AS service_name,
  JSON_VALUE(json_payload, '$."deployment.environment.name"') AS environment_name,
  JSON_VALUE(json_payload, '$."event.name"') AS event_name,
  JSON_VALUE(json_payload, '$."error.type"') AS error_type,
  JSON_VALUE(json_payload, '$."error.handled"') AS error_handled,
  REGEXP_EXTRACT_ALL(
    REGEXP_REPLACE(
      JSON_VALUE(json_payload, '$."error.stack"'), @chained_exception_pattern, ''
    ),
    @frame_pattern
  ) AS frames,
  COALESCE(LENGTH(JSON_VALUE(json_payload, '$."error.stack"')) >= 16384, FALSE)
    AS stack_truncated,
  ARRAY_TO_STRING(
    ARRAY(
      SELECT LOWER(word)
      FROM UNNEST(
        REGEXP_EXTRACT_ALL(
          REGEXP_REPLACE(
            REGEXP_REPLACE(
              JSON_VALUE(json_payload, '$.message'), @double_quoted_pattern, ''
            ),
            @single_quoted_pattern,
            r'\1'
          ),
          @template_word_pattern
        )
      ) AS word WITH OFFSET AS position
      WHERE position < 3
      ORDER BY position
    ),
    ' '
  ) AS message_template,
  JSON_VALUE(json_payload, '$.attributes.error_type') AS attribute_error_type,
  JSON_VALUE(json_payload, '$.attributes.failure_category') AS failure_category,
  JSON_VALUE(json_payload, '$."http.route"') AS route,
  JSON_VALUE(json_payload, '$."http.response.status_code"') AS status_code,
  JSON_VALUE(json_payload, '$."operation.name"') AS operation_name,
  TO_HEX(SHA256(JSON_VALUE(json_payload, '$."request.id"'))) AS request_key,
  TO_HEX(SHA256(JSON_VALUE(json_payload, '$.attributes.observability_id')))
    AS observability_key,
  TO_HEX(SHA256(COALESCE(
    JSON_VALUE(json_payload, '$.trace_id'),
    REGEXP_EXTRACT(trace, r'/traces/([0-9A-Fa-f]+)$')
  ))) AS trace_key
FROM `_AllLogs`
WHERE timestamp >= @query_start AND timestamp < @window_end
  AND JSON_VALUE(json_payload, '$.schema_version') = 'policyengine.observability.v2'
  AND JSON_VALUE(json_payload, '$."service.namespace"') = 'policyengine.api-v1'
  AND severity_number >= 500
  AND COALESCE(JSON_VALUE(json_payload, '$."http.route"'), '')
    NOT IN UNNEST(@excluded_routes)
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY insert_id, timestamp ORDER BY receive_timestamp
) = 1
"""

REQUEST_COUNTS_QUERY = r"""
WITH completed_requests AS (
  SELECT
    JSON_VALUE(json_payload, '$."service.name"') AS service_name,
    JSON_VALUE(json_payload, '$."deployment.environment.name"') AS environment_name,
    JSON_VALUE(json_payload, '$."http.route"') AS route
  FROM `_AllLogs`
  WHERE timestamp >= @window_start AND timestamp < @window_end
    AND JSON_VALUE(json_payload, '$.schema_version') = 'policyengine.observability.v2'
    AND JSON_VALUE(json_payload, '$."service.namespace"') = 'policyengine.api-v1'
    AND JSON_VALUE(json_payload, '$."event.name"') = 'request.completed'
    AND COALESCE(JSON_VALUE(json_payload, '$."http.route"'), '')
      NOT IN UNNEST(@excluded_routes)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY insert_id, timestamp ORDER BY receive_timestamp
  ) = 1
)
SELECT service_name, environment_name, route, COUNT(*) AS requests
FROM completed_requests
GROUP BY service_name, environment_name, route
"""


class ReportingWindow(NamedTuple):
    """One Eastern calendar day, as the half-open interval [start, end)."""

    start: datetime
    end: datetime

    @property
    def hours(self) -> float:
        """Return the elapsed hours: 23 or 25 on the days the clocks change."""
        return _hours_between(self.start, self.end)

    @property
    def lookback_start(self) -> datetime:
        """Return midnight Eastern seven days before the window starts."""
        return self.start - LOOKBACK

    @property
    def lookback_hours(self) -> float:
        """Return the elapsed hours of the seven days before the window."""
        return _hours_between(self.lookback_start, self.start)


def _hours_between(start: datetime, end: datetime) -> float:
    # Subtracting two datetimes in the same zone ignores a clock change, so
    # compare them in UTC.
    return (end.astimezone(UTC) - start.astimezone(UTC)) / timedelta(hours=1)


def reporting_window(report_date: date) -> ReportingWindow:
    """Return the window from midnight Eastern on ``report_date`` to the next."""
    next_date = report_date + timedelta(days=1)
    return ReportingWindow(
        start=datetime.combine(report_date, MIDNIGHT, tzinfo=REPORTING_TIME_ZONE),
        end=datetime.combine(next_date, MIDNIGHT, tzinfo=REPORTING_TIME_ZONE),
    )


def default_report_date(now: datetime) -> date:
    """Return the most recent Eastern calendar day that ended before ``now``."""
    return now.astimezone(REPORTING_TIME_ZONE).date() - timedelta(days=1)


def service_family(service_name: str) -> str:
    """Return the service name, merging versioned simulation services into one."""
    return VERSIONED_SIMULATION_SERVICE.sub(r"\1", service_name)


def environment_class(environment_name: str | None) -> str:
    """Classify a deployment environment name as production, staging or other.

    The Modal gateway reports its production environment as ``main``.
    """
    if environment_name in PRODUCTION_ENVIRONMENT_NAMES:
        return "production"
    if environment_name in STAGING_ENVIRONMENT_NAMES:
        return "staging"
    return "other"


def normalize_path(path: str) -> str:
    """Return a source path without its installation or checkout prefix."""
    installed = INSTALLED_PACKAGE_PREFIX.sub("", path, count=1)
    if installed != path:
        return installed
    application = APPLICATION_PATH_IN_ABSOLUTE_PATH.search(path)
    if application:
        return application.group(1)
    standard_library = STANDARD_LIBRARY_PREFIX.sub("", path, count=1)
    if standard_library != path:
        return standard_library
    return "/".join(path.split("/")[-FALLBACK_PATH_COMPONENTS:])


def frame_key(frame: str) -> str | None:
    """Return ``path:function`` for one ``FRAME_PATTERN`` match, without its line."""
    parts = FRAME_PARTS.match(frame)
    if parts is None:
        return None
    return f"{normalize_path(parts['path'])}:{parts['function']}"


def fingerprint_frames(frames: Iterable[str] | None) -> tuple[str, ...]:
    """Choose the frames that identify where an exception was raised.

    ``frames`` come from the first traceback of the stack only (see
    ``CHAINED_EXCEPTION_PATTERN``); for a chained exception that is its first
    cause. These are the three innermost frames in application packages.
    Without application frames they are the three innermost frames of any
    kind, and without a stack, a placeholder.
    """
    keys = [key for key in map(frame_key, frames or ()) if key is not None]
    if not keys:
        return (MISSING,)
    application_keys = [key for key in keys if APPLICATION_PATH.match(key)]
    return tuple((application_keys or keys)[-FINGERPRINT_FRAME_COUNT:])


def _validated(value: str | None, pattern: re.Pattern[str], max_length: int) -> str:
    if not value:
        return MISSING
    if len(value) <= max_length and pattern.fullmatch(value):
        return value
    return UNRECOGNIZED


def public_error_type(value: str | None) -> str:
    """Return an exception class name, or a placeholder for anything else."""
    return _validated(value, ERROR_TYPE_PATTERN, MAX_ERROR_TYPE_LENGTH)


def public_family(value: str | None) -> str:
    """Return a service name or family, or a placeholder for anything else."""
    return _validated(value, FAMILY_PATTERN, MAX_FAMILY_LENGTH)


def public_operation(value: str | None) -> str:
    """Return a code-defined operation name, or a placeholder for anything else."""
    return _validated(value, OPERATION_PATTERN, MAX_OPERATION_LENGTH)


def _route_segment_is_code(segment: str) -> bool:
    if ROUTE_PARAMETER.match(segment):
        return True
    digits = sum(character.isdigit() for character in segment)
    return bool(ROUTE_LITERAL.match(segment)) and digits <= MAX_ROUTE_LITERAL_DIGITS


def public_route(value: str | None) -> str:
    """Return a route template, or a placeholder for anything else.

    A path that holds a record ID, a query string or free text is not a
    template, so it never reaches public output.
    """
    if not value:
        return MISSING
    if value == UNMATCHED_ROUTE:
        return value
    if len(value) > MAX_ROUTE_LENGTH or not value.startswith("/"):
        return UNRECOGNIZED
    segments = [segment for segment in value.split("/") if segment]
    if all(map(_route_segment_is_code, segments)):
        return value
    return UNRECOGNIZED


def public_status(value: object) -> int | None:
    """Return an HTTP status code as an integer, or None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if isinstance(value, int) and LOWEST_HTTP_STATUS <= value <= HIGHEST_HTTP_STATUS:
        return value
    return None


@dataclass(frozen=True)
class ErrorRecord:
    """One ERROR record from the central log bucket, as the query returns it.

    The query returns identifiers only as SHA-256 hashes, stacks only as frame
    headers, and messages only as their first few words.
    """

    timestamp: datetime
    service_name: str
    environment_name: str | None
    event_name: str | None
    error_type: str | None
    error_handled: bool | None
    frames: tuple[str, ...]
    stack_truncated: bool
    message_template: str | None
    attribute_error_type: str | None
    failure_category: str | None
    route: str | None
    status_code: int | None
    operation_name: str | None
    request_key: str | None
    observability_key: str | None
    trace_key: str | None

    @property
    def family(self) -> str:
        """Return the service family that produced the record."""
        return service_family(self.service_name)

    @property
    def environment(self) -> str:
        """Return production, staging or other."""
        return environment_class(self.environment_name)

    @property
    def kind(self) -> str:
        """Return exception, message or failed_request.

        A record with an exception type is an exception, even a
        ``request.completed`` record. Any other ``request.completed`` record is
        a request that failed without a recorded exception.
        """
        if self.error_type:
            return "exception"
        if self.event_name == REQUEST_COMPLETED_EVENT:
            return "failed_request"
        return "message"


def _primary_preference(record: ErrorRecord) -> tuple[int, int, datetime]:
    """Sort key: exceptions before messages before request completions.

    Among exceptions, an unhandled one (the cause of an error response) comes
    first; otherwise the earliest record does.
    """
    if record.event_name == REQUEST_COMPLETED_EVENT:
        source_rank = 2
    elif record.error_type:
        source_rank = 0
    else:
        source_rank = 1
    handled_rank = 0 if record.error_handled is False else 1
    return source_rank, handled_rank, record.timestamp


def primary_records(records: Iterable[ErrorRecord]) -> list[ErrorRecord]:
    """Return one record per failure, in time order.

    Records of one service that share a request ID, or a trace when there is no
    request ID, describe one failure. A record with neither is its own failure.
    """
    failures: dict[tuple[str, str], list[ErrorRecord]] = {}
    standalone: list[ErrorRecord] = []
    for record in records:
        correlation = record.request_key or record.trace_key
        if correlation is None:
            standalone.append(record)
        else:
            failures.setdefault((record.family, correlation), []).append(record)
    chosen = [min(group, key=_primary_preference) for group in failures.values()]
    return sorted([*chosen, *standalone], key=lambda record: record.timestamp)


def fingerprint_parts(record: ErrorRecord) -> tuple[str, ...]:
    """Return the kind and the values that identify the record's error group.

    An exception's route is left out, so one shared failure doesn't open an
    issue for every route that reaches it.
    """
    kind = record.kind
    if kind == "exception":
        return (
            kind,
            record.family,
            record.error_type or MISSING,
            *fingerprint_frames(record.frames),
        )
    if kind == "message":
        return (
            kind,
            record.family,
            record.route or record.operation_name or MISSING,
            record.message_template or MISSING,
            record.attribute_error_type or MISSING,
            record.failure_category or MISSING,
        )
    status = MISSING if record.status_code is None else str(record.status_code)
    return (kind, record.family, record.route or MISSING, status)


def fingerprint_key(secret: str) -> bytes:
    """Return the HMAC key, rejecting a secret too short to be random."""
    if len(secret) < MIN_FINGERPRINT_KEY_LENGTH:
        msg = (
            "the fingerprint key must be at least "
            f"{MIN_FINGERPRINT_KEY_LENGTH} characters"
        )
        raise ValueError(msg)
    return secret.encode()


def fingerprint(record: ErrorRecord, key: bytes) -> str:
    """Return the record's error group as 16 hex characters of HMAC-SHA256.

    The key keeps anyone from confirming a guessed message or stack frame by
    hashing it and comparing the result with a public fingerprint.
    """
    payload = json.dumps(
        [FINGERPRINT_ALGORITHM, *fingerprint_parts(record)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return digest[:FINGERPRINT_LENGTH]


class RequestCount(NamedTuple):
    """Requests that one service completed on one route during the window."""

    service_name: str
    environment_name: str | None
    route: str | None
    requests: int


class Occurrence(NamedTuple):
    """One failure in an error group."""

    timestamp: datetime
    environment: str
    route: str | None
    affected_key: str
    observability_key: str | None
    trace_key: str | None


@dataclass(frozen=True)
class EnvironmentMeasures:
    """An error group's measures in one environment.

    Counts and rates cover the window; first and last seen cover the window
    and the seven days before it.
    """

    occurrences: int
    affected_requests: int
    observability_ids: int
    route_affected_requests: int
    route_requests: int
    error_rate: float | None
    hourly_rate: float
    previous_hourly_rate: float
    first_seen: datetime | None
    last_seen: datetime | None


@dataclass(frozen=True)
class ErrorGroup:
    """Failures that share a fingerprint, described only by validated values."""

    fingerprint: str
    kind: str
    family: str
    error_type: str
    route: str
    status_code: int | None
    operation: str
    production: EnvironmentMeasures
    staging: EnvironmentMeasures
    related_fingerprints: tuple[str, ...]
    occurrences: tuple[Occurrence, ...]

    def production_since(self, moment: datetime) -> tuple[int, int]:
        """Return production occurrences and affected requests from ``moment``."""
        recent = [
            occurrence
            for occurrence in self.occurrences
            if occurrence.environment == "production" and occurrence.timestamp >= moment
        ]
        return len(recent), len({occurrence.affected_key for occurrence in recent})


def _occurrence(record: ErrorRecord, position: int) -> Occurrence:
    """Describe a failure, identifying what it affected as precisely as possible.

    The affected request is the request ID, else the observability ID, else the
    trace. A failure with none of them counts as its own request.
    """
    if record.request_key:
        affected_key = f"request:{record.request_key}"
    elif record.observability_key:
        affected_key = f"observability:{record.observability_key}"
    elif record.trace_key:
        affected_key = f"trace:{record.trace_key}"
    else:
        affected_key = f"record:{position}"
    return Occurrence(
        timestamp=record.timestamp,
        environment=record.environment,
        route=record.route,
        affected_key=affected_key,
        observability_key=record.observability_key,
        trace_key=record.trace_key,
    )


class RouteRequests:
    """Requests completed in the window, per service family, environment and route."""

    def __init__(self, request_counts: Iterable[RequestCount]) -> None:
        """Add up the request counts, merging versioned simulation services."""
        self._totals: Counter[tuple[str, str, str | None]] = Counter()
        for count in request_counts:
            environment = environment_class(count.environment_name)
            family = service_family(count.service_name)
            self._totals[family, environment, count.route] += count.requests

    def total(self, family: str, environment: str, routes: Iterable[str]) -> int:
        """Return the requests one service family completed on the given routes."""
        return sum(self._totals[family, environment, route] for route in routes)


def _related_fingerprints(
    occurrences_by_group: dict[str, list[Occurrence]],
) -> dict[str, tuple[str, ...]]:
    """For each group, the groups that share the most traces with it."""
    groups_by_trace: dict[str, set[str]] = {}
    for group, occurrences in occurrences_by_group.items():
        for occurrence in occurrences:
            if occurrence.trace_key:
                groups_by_trace.setdefault(occurrence.trace_key, set()).add(group)
    related: dict[str, tuple[str, ...]] = {}
    for group, occurrences in occurrences_by_group.items():
        shared_traces: Counter[str] = Counter()
        traces = {occurrence.trace_key for occurrence in occurrences}
        for trace in traces - {None}:
            shared_traces.update(groups_by_trace[trace] - {group})
        ranked = sorted(shared_traces, key=lambda other: (-shared_traces[other], other))
        related[group] = tuple(ranked[:MAX_RELATED_FINGERPRINTS])
    return related


def _environment_measures(
    occurrences: list[Occurrence],
    environment: str,
    family: str,
    route_requests: RouteRequests,
    window: ReportingWindow,
) -> EnvironmentMeasures:
    in_environment = [item for item in occurrences if item.environment == environment]
    in_window = [item for item in in_environment if item.timestamp >= window.start]
    before_window = len(in_environment) - len(in_window)
    affected_requests = len({item.affected_key for item in in_window})
    # The error rate compares failed requests with completed requests on the
    # same routes, so failures without a route, such as background
    # operations, are left out of both.
    on_routes = [item for item in in_window if item.route]
    route_affected_requests = len({item.affected_key for item in on_routes})
    routes = {item.route for item in on_routes}
    requests = route_requests.total(family, environment, routes)
    timestamps = [item.timestamp for item in in_environment]
    return EnvironmentMeasures(
        occurrences=len(in_window),
        affected_requests=affected_requests,
        observability_ids=len(
            {item.observability_key for item in in_window if item.observability_key}
        ),
        route_affected_requests=route_affected_requests,
        route_requests=requests,
        error_rate=route_affected_requests / requests if requests else None,
        hourly_rate=len(in_window) / window.hours,
        previous_hourly_rate=before_window / window.lookback_hours,
        first_seen=min(timestamps, default=None),
        last_seen=max(timestamps, default=None),
    )


def _most_frequent_route(occurrences: list[Occurrence], window: ReportingWindow) -> str:
    """Return the route most failures in the window used, preferring production."""
    in_window = [item for item in occurrences if item.timestamp >= window.start]
    production = [item for item in in_window if item.environment == "production"]
    routes = Counter(item.route for item in production or in_window)
    route, _ = min(routes.items(), key=lambda item: (-item[1], item[0] or ""))
    return public_route(route)


def _error_group(
    group_fingerprint: str,
    members: list[tuple[ErrorRecord, Occurrence]],
    related_fingerprints: tuple[str, ...],
    route_requests: RouteRequests,
    window: ReportingWindow,
) -> ErrorGroup:
    example = members[0][0]
    occurrences = [occurrence for _, occurrence in members]
    measures = {
        environment: _environment_measures(
            occurrences, environment, example.family, route_requests, window
        )
        for environment in REPORTED_ENVIRONMENTS
    }
    return ErrorGroup(
        fingerprint=group_fingerprint,
        kind=example.kind,
        family=public_family(example.family),
        error_type=public_error_type(example.error_type),
        route=_most_frequent_route(occurrences, window),
        status_code=public_status(example.status_code),
        operation=public_operation(example.operation_name),
        production=measures["production"],
        staging=measures["staging"],
        related_fingerprints=related_fingerprints,
        occurrences=tuple(occurrences),
    )


def build_groups(
    records: Iterable[ErrorRecord],
    request_counts: Iterable[RequestCount],
    window: ReportingWindow,
    key: bytes,
) -> list[ErrorGroup]:
    """Group the failures in production and staging and measure each group.

    Only groups with a failure in the window are returned, most production
    occurrences first.
    """
    in_scope = [
        record
        for record in records
        if record.environment in REPORTED_ENVIRONMENTS
        and window.lookback_start <= record.timestamp < window.end
    ]
    members_by_group: dict[str, list[tuple[ErrorRecord, Occurrence]]] = {}
    for position, record in enumerate(primary_records(in_scope)):
        members_by_group.setdefault(fingerprint(record, key), []).append(
            (record, _occurrence(record, position))
        )
    related = _related_fingerprints(
        {
            group: [occurrence for _, occurrence in members]
            for group, members in members_by_group.items()
        }
    )
    route_requests = RouteRequests(request_counts)
    groups = [
        _error_group(group, members, related[group], route_requests, window)
        for group, members in members_by_group.items()
        if any(occurrence.timestamp >= window.start for _, occurrence in members)
    ]
    return sorted(
        groups,
        key=lambda group: (
            -group.production.occurrences,
            -group.staging.occurrences,
            group.fingerprint,
        ),
    )


class HttpRequest(NamedTuple):
    """An HTTP request for a transport to send."""

    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None


class HttpResponse(NamedTuple):
    """An HTTP response, including error responses. Header names are lowercase."""

    status: int
    reason: str
    headers: Mapping[str, str]
    body: bytes


def urllib_transport(request: HttpRequest) -> HttpResponse:
    """Send a request with the standard library, returning HTTP errors too."""
    outgoing = Request(
        request.url,
        data=request.body,
        headers=request.headers,
        method=request.method,
    )
    try:
        response = urlopen(outgoing, timeout=HTTP_TIMEOUT_SECONDS)
    except HTTPError as error:
        with error:
            return HttpResponse(
                status=error.code,
                reason=str(error.reason),
                headers={name.lower(): value for name, value in error.headers.items()},
                body=error.read(),
            )
    with response:
        return HttpResponse(
            status=response.status,
            reason=response.reason,
            headers={name.lower(): value for name, value in response.headers.items()},
            body=response.read(),
        )


class ApiError(Exception):
    """An API request failed. The text holds only code-defined values."""

    service = "API"

    def __init__(
        self, message: str, *, status: int | None = None, reason: str | None = None
    ) -> None:
        """Keep the HTTP status and reason for the caller's summary."""
        super().__init__(message)
        self.status = status
        self.reason = reason

    @classmethod
    def from_response(cls, response: HttpResponse) -> ApiError:
        """Describe an error response by its status and reason, never its body."""
        reason = _error_reason(response)
        message = f"{cls.service} request failed: HTTP {response.status} {reason}"
        return cls(message, status=response.status, reason=reason)


class BigQueryError(ApiError):
    """A BigQuery request failed."""

    service = "BigQuery"


class BigQueryTimeoutError(BigQueryError):
    """A BigQuery query job didn't complete within the polling limit."""


def _error_reason(response: HttpResponse) -> str:
    """Return a Google API error's reason code, else the HTTP reason phrase."""
    try:
        payload = json.loads(response.body)
        reason = payload["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        reason = None
    for candidate in (reason, response.reason):
        if isinstance(candidate, str) and ERROR_REASON_PATTERN.match(candidate):
            return candidate
    return "unknown"


def _bigquery_boolean(text: str) -> bool:
    return text == "true"


def _bigquery_timestamp(text: str) -> datetime:
    """Convert microseconds since the epoch, as ``useInt64Timestamp`` returns."""
    return UNIX_EPOCH + timedelta(microseconds=int(text))


CELL_CONVERTERS: dict[str, Callable[[str], object]] = {
    "INTEGER": int,
    "INT64": int,
    "FLOAT": float,
    "FLOAT64": float,
    "BOOLEAN": _bigquery_boolean,
    "BOOL": _bigquery_boolean,
    "TIMESTAMP": _bigquery_timestamp,
}


def _convert_cell(field: Mapping[str, Any], value: object) -> object:
    """Convert one BigQuery REST value, which arrives as a string, to Python."""
    if value is None:
        return None
    if field.get("mode") == "REPEATED" and isinstance(value, list):
        item_field = {**field, "mode": "NULLABLE"}
        return [_convert_cell(item_field, item["v"]) for item in value]
    converter = CELL_CONVERTERS.get(str(field.get("type")), str)
    return converter(str(value))


def _convert_rows(response: Mapping[str, Any]) -> list[dict[str, object]]:
    fields = response["schema"]["fields"]
    return [
        {
            field["name"]: _convert_cell(field, cell["v"])
            for field, cell in zip(fields, row["f"], strict=True)
        }
        for row in response.get("rows", [])
    ]


class BigQueryClient:
    """Runs parameterized standard SQL queries through the BigQuery REST API."""

    def __init__(
        self,
        project_id: str,
        access_token: str,
        transport: Callable[[HttpRequest], HttpResponse] = urllib_transport,
    ) -> None:
        """Run jobs in ``project_id`` against its linked log dataset."""
        self.project_id = project_id
        self._access_token = access_token
        self._transport = transport
        self._queries_url = (
            f"{BIGQUERY_API}/projects/{quote(project_id, safe='')}/queries"
        )

    def query(
        self, sql: str, parameters: list[dict[str, Any]], label: str
    ) -> list[dict[str, object]]:
        """Run ``sql`` and return every row as a dictionary of converted values."""
        body = {
            "query": sql,
            "useLegacySql": False,
            "parameterMode": "NAMED",
            "queryParameters": parameters,
            "defaultDataset": {
                "projectId": self.project_id,
                "datasetId": LINKED_DATASET,
            },
            "maximumBytesBilled": str(MAXIMUM_BYTES_BILLED),
            "labels": {"purpose": "telemetry-error-issues", "query": label},
            "timeoutMs": QUERY_WAIT_MILLISECONDS,
            "formatOptions": {"useInt64Timestamp": True},
        }
        response = self._send("POST", self._queries_url, body)
        job = response["jobReference"]
        for _ in range(MAX_QUERY_POLLS):
            if response.get("jobComplete"):
                break
            response = self._results(job, page_token=None)
        else:
            msg = "BigQuery query did not complete in time"
            raise BigQueryTimeoutError(msg)
        rows = _convert_rows(response)
        while response.get("pageToken"):
            response = self._results(job, page_token=response["pageToken"])
            rows.extend(_convert_rows(response))
        return rows

    def _results(
        self, job: Mapping[str, str], page_token: str | None
    ) -> dict[str, Any]:
        parameters = {
            "location": job["location"],
            "timeoutMs": str(QUERY_WAIT_MILLISECONDS),
            "formatOptions.useInt64Timestamp": "true",
        }
        if page_token:
            parameters["pageToken"] = page_token
        job_id = quote(job["jobId"], safe="")
        url = f"{self._queries_url}/{job_id}?{urlencode(parameters)}"
        return self._send("GET", url, None)

    def _send(
        self, method: str, url: str, body: Mapping[str, object] | None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._access_token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        encoded = None if body is None else json.dumps(body).encode()
        response = self._transport(HttpRequest(method, url, headers, encoded))
        if response.status >= HTTPStatus.BAD_REQUEST:
            raise BigQueryError.from_response(response)
        return json.loads(response.body)


def _timestamp_parameter(name: str, moment: datetime) -> dict[str, Any]:
    return {
        "name": name,
        "parameterType": {"type": "TIMESTAMP"},
        "parameterValue": {"value": moment.astimezone(UTC).isoformat(sep=" ")},
    }


def _query_parameters(
    timestamps: Mapping[str, datetime], strings: Mapping[str, str]
) -> list[dict[str, Any]]:
    parameters = [
        _timestamp_parameter(name, value) for name, value in timestamps.items()
    ]
    parameters.extend(
        {
            "name": name,
            "parameterType": {"type": "STRING"},
            "parameterValue": {"value": value},
        }
        for name, value in strings.items()
    )
    parameters.append(
        {
            "name": "excluded_routes",
            "parameterType": {"type": "ARRAY", "arrayType": {"type": "STRING"}},
            "parameterValue": {
                "arrayValues": [{"value": route} for route in HEALTH_CHECK_ROUTES]
            },
        }
    )
    return parameters


def _text(value: object) -> str | None:
    return None if value is None or value == "" else str(value)


def _integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def _boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return {"true": True, "false": False}.get(str(value))


def error_record_from_row(row: Mapping[str, object]) -> ErrorRecord:
    """Build an ``ErrorRecord`` from one row of ``ERROR_RECORDS_QUERY``."""
    timestamp = row["timestamp"]
    if not isinstance(timestamp, datetime):
        msg = "an error record has no timestamp"
        raise TypeError(msg)
    frames = row["frames"]
    return ErrorRecord(
        timestamp=timestamp,
        service_name=_text(row["service_name"]) or MISSING,
        environment_name=_text(row["environment_name"]),
        event_name=_text(row["event_name"]),
        error_type=_text(row["error_type"]),
        error_handled=_boolean(row["error_handled"]),
        frames=tuple(map(str, frames)) if isinstance(frames, list) else (),
        stack_truncated=row["stack_truncated"] is True,
        message_template=_text(row["message_template"]),
        attribute_error_type=_text(row["attribute_error_type"]),
        failure_category=_text(row["failure_category"]),
        route=_text(row["route"]),
        status_code=_integer(row["status_code"]),
        operation_name=_text(row["operation_name"]),
        request_key=_text(row["request_key"]),
        observability_key=_text(row["observability_key"]),
        trace_key=_text(row["trace_key"]),
    )


def fetch_error_records(
    client: BigQueryClient, window: ReportingWindow
) -> list[ErrorRecord]:
    """Return the ERROR records of the window and the seven days before it."""
    parameters = _query_parameters(
        {"query_start": window.lookback_start, "window_end": window.end},
        {
            "frame_pattern": FRAME_PATTERN,
            "chained_exception_pattern": CHAINED_EXCEPTION_PATTERN,
            "double_quoted_pattern": DOUBLE_QUOTED_PATTERN,
            "single_quoted_pattern": SINGLE_QUOTED_PATTERN,
            "template_word_pattern": TEMPLATE_WORD_PATTERN,
        },
    )
    rows = client.query(ERROR_RECORDS_QUERY, parameters, "error-records")
    return [error_record_from_row(row) for row in rows]


def fetch_request_counts(
    client: BigQueryClient, window: ReportingWindow
) -> list[RequestCount]:
    """Return the requests each service completed per route in the window."""
    parameters = _query_parameters(
        {"window_start": window.start, "window_end": window.end}, {}
    )
    rows = client.query(REQUEST_COUNTS_QUERY, parameters, "request-counts")
    return [
        RequestCount(
            service_name=_text(row["service_name"]) or MISSING,
            environment_name=_text(row["environment_name"]),
            route=_text(row["route"]),
            requests=_integer(row["requests"]) or 0,
        )
        for row in rows
    ]


def _code(value: str) -> str:
    return f"`{value}`"


def _place(group: ErrorGroup) -> str:
    """Describe where the group fails: its route, else its operation, else nothing."""
    if group.route != MISSING:
        return f" on {_code(group.route)}"
    if group.kind == "message" and group.operation != MISSING:
        return f" in {_code(group.operation)}"
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


def logs_explorer_url(
    group: ErrorGroup, window: ReportingWindow, project_id: str
) -> str:
    """Return a Logs Explorer link to the group's records in the window."""
    query = "\n".join(
        [
            *_logs_filters(group),
            f'timestamp>="{_logs_timestamp(window.start)}"',
            f'timestamp<"{_logs_timestamp(window.end)}"',
        ]
    )
    view = (
        f"projects/{project_id}/locations/global/buckets/{LOG_BUCKET}/views/{LOG_VIEW}"
    )
    settings = {"query": query, "storageScope": f"storage,{view}"}
    encoded = "".join(
        f";{name}={quote(value, safe='')}" for name, value in settings.items()
    )
    return f"{LOGS_EXPLORER_URL}{encoded}?{urlencode({'project': project_id})}"


def _eastern_time(moment: datetime | None) -> str:
    if moment is None:
        return NOT_AVAILABLE
    return moment.astimezone(REPORTING_TIME_ZONE).strftime("%Y-%m-%d %H:%M %Z")


def _window_text(window: ReportingWindow) -> str:
    return (
        f"{_eastern_time(window.start)} to {_eastern_time(window.end)} "
        f"({window.hours:.0f} hours)"
    )


def _error_rate(measures: EnvironmentMeasures) -> str:
    if measures.error_rate is None:
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
            lambda measures: _eastern_time(measures.first_seen),
        ),
        ("Last seen", lambda measures: _eastern_time(measures.last_seen)),
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
        f"- Service: {_code(group.family)}",
    ]
    if group.kind == "exception":
        details.append(f"- Exception type: {_code(group.error_type)}")
    if group.kind == "failed_request":
        details.append(f"- Response: {_status_text(group)}")
    if group.kind == "message" and group.operation != MISSING:
        details.append(f"- Operation: {_code(group.operation)}")
    details.append(f"- Most frequent route: {_code(group.route)}")
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


def issue_section(group: ErrorGroup, window: ReportingWindow, project_id: str) -> str:
    """Return the marked section of the issue body, which each run replaces."""
    related = ", ".join(map(_code, group.related_fingerprints))
    lines = [
        SECTION_START,
        f"### Error group {_code(group.fingerprint)}",
        "",
        *_group_details(group),
        f"- Window: {_window_text(window)}",
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
            f"({logs_explorer_url(group, window, project_id)}), for the window only. "
            f"It needs read access to the `{project_id}` project."
        ),
        "",
        _state_comment(group, window),
        SECTION_END,
    ]
    return "\n".join(lines)


def issue_body(group: ErrorGroup, window: ReportingWindow, project_id: str) -> str:
    """Return a new issue's body: a short note, then the marked section."""
    note = (
        "The daily telemetry error report opened this issue for a production "
        "error group. Each run replaces the marked section below with the "
        "latest day's measures; text outside it is kept."
    )
    return f"{note}\n\n{issue_section(group, window, project_id)}\n"


class GitHubError(ApiError):
    """A GitHub request failed."""

    service = "GitHub"


class GitHubLabelError(GitHubError):
    """GitHub didn't apply the labels the job asked for."""


def _rate_limit_wait(response: HttpResponse) -> int | None:
    """Return the seconds to wait before retrying a rate-limited request.

    A 403 without ``retry-after`` is a permission failure, so it isn't retried.
    """
    if response.status not in RATE_LIMIT_STATUSES:
        return None
    retry_after = response.headers.get("retry-after", "")
    if retry_after.isascii() and retry_after.isdigit():
        seconds = int(retry_after)
    elif response.status == HTTPStatus.TOO_MANY_REQUESTS:
        seconds = DEFAULT_RATE_LIMIT_WAIT_SECONDS
    else:
        return None
    return seconds if seconds <= MAX_RATE_LIMIT_WAIT_SECONDS else None


def _json_object(response: HttpResponse) -> dict[str, Any]:
    payload = json.loads(response.body)
    if not isinstance(payload, dict):
        msg = "GitHub returned an unexpected response"
        raise GitHubError(msg)
    return payload


def _json_list(response: HttpResponse) -> list[dict[str, Any]]:
    payload = json.loads(response.body)
    if not isinstance(payload, list):
        msg = "GitHub returned an unexpected response"
        raise GitHubError(msg)
    return payload


class GitHubClient:
    """Reads and writes one repository's issues and labels.

    Writes go one at a time, at least a second apart. A rate-limited request is
    retried after the wait GitHub asks for, up to three times.
    """

    def __init__(
        self,
        repository: str,
        credential: str,
        transport: Callable[[HttpRequest], HttpResponse] = urllib_transport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Send requests for ``repository`` (``owner/name``) with ``credential``."""
        self._repository_url = f"{GITHUB_API}/repos/{repository}"
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {credential}",
            "User-Agent": "policyengine-telemetry-error-issues",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._last_write: float | None = None

    def list_issues(self, creator: str) -> list[dict[str, Any]]:
        """Return the open and closed issues ``creator`` opened, without PRs."""
        issues = self._pages("/issues", {"state": "all", "creator": creator})
        return [issue for issue in issues if "pull_request" not in issue]

    def list_labels(self) -> set[str]:
        """Return the names of the repository's labels."""
        return {label["name"] for label in self._pages("/labels", {})}

    def create_label(self, name: str, color: str, description: str) -> None:
        """Create a label."""
        self._send(
            "POST",
            "/labels",
            {"name": name, "color": color, "description": description},
        )

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict[str, Any]:
        """Open an issue and return it as GitHub describes it."""
        payload = {"title": title, "body": body, "labels": labels}
        return _json_object(self._send("POST", "/issues", payload))

    def update_issue(self, number: int, fields: Mapping[str, object]) -> None:
        """Change an issue's fields, such as its body or state."""
        self._send("PATCH", f"/issues/{number}", fields)

    def add_labels(self, number: int, labels: list[str]) -> set[str]:
        """Add labels to an issue and return all the labels it now has."""
        response = self._send("POST", f"/issues/{number}/labels", {"labels": labels})
        return {label["name"] for label in _json_list(response)}

    def add_comment(self, number: int, body: str) -> None:
        """Comment on an issue."""
        self._send("POST", f"/issues/{number}/comments", {"body": body})

    def _pages(self, path: str, parameters: Mapping[str, str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urlencode(
                {**parameters, "per_page": GITHUB_PAGE_SIZE, "page": page}
            )
            batch = _json_list(self._send("GET", f"{path}?{query}", None))
            items.extend(batch)
            if len(batch) < GITHUB_PAGE_SIZE:
                return items
            page += 1

    def _wait_between_writes(self) -> None:
        if self._last_write is None:
            return
        elapsed = self._clock() - self._last_write
        if elapsed < MIN_SECONDS_BETWEEN_WRITES:
            self._sleep(MIN_SECONDS_BETWEEN_WRITES - elapsed)

    def _send(
        self, method: str, path: str, body: Mapping[str, object] | None
    ) -> HttpResponse:
        headers = dict(self._headers)
        encoded = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded = json.dumps(body).encode()
        request = HttpRequest(method, f"{self._repository_url}{path}", headers, encoded)
        is_write = method != "GET"
        for retry in range(MAX_RATE_LIMIT_RETRIES + 1):
            if is_write:
                self._wait_between_writes()
            response = self._transport(request)
            if is_write:
                self._last_write = self._clock()
            wait = _rate_limit_wait(response)
            if wait is None or retry == MAX_RATE_LIMIT_RETRIES:
                break
            self._sleep(wait)
        if response.status >= HTTPStatus.BAD_REQUEST:
            raise GitHubError.from_response(response)
        return response


class SyncAction(NamedTuple):
    """What one run did, or in a dry run would do, for one error group."""

    fingerprint: str
    kind: str
    family: str
    production_occurrences: int
    staging_occurrences: int
    issue_number: int | None
    action: str


class SyncResult(NamedTuple):
    """Every group's action, and how many new issues waited for a later run."""

    actions: list[SyncAction]
    deferred: int


def replace_section(body: str, section: str) -> str:
    """Replace the marked section of ``body``, or add it at the end if missing."""
    start = body.find(SECTION_START)
    end = body.find(SECTION_END, start) if start >= 0 else -1
    if end >= 0:
        return f"{body[:start]}{section}{body[end + len(SECTION_END) :]}"
    kept = body.rstrip()
    return f"{kept}\n\n{section}\n" if kept else f"{section}\n"


def _issue_fingerprint(issue: Mapping[str, Any]) -> str | None:
    """Return the fingerprint from the state comment, or else from the title."""
    state = parse_state(issue.get("body") or "")
    if state and state.get("algorithm") == FINGERPRINT_ALGORITHM:
        fingerprint_value = state.get("fingerprint")
        if isinstance(fingerprint_value, str):
            return fingerprint_value
    title = issue.get("title") or ""
    match = TITLE_FINGERPRINT.search(title)
    if match and title.startswith(ISSUE_TITLE_PREFIX):
        return match.group(1)
    return None


def _issues_by_fingerprint(
    issues: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    """Index the bot's issues by fingerprint, preferring open, then newest."""
    index: dict[str, Mapping[str, Any]] = {}
    for issue in issues:
        if (issue.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        group = _issue_fingerprint(issue)
        if group is None:
            continue
        rank = (issue.get("state") == "open", issue.get("number", 0))
        current = index.get(group)
        if current is None or rank > (
            current.get("state") == "open",
            current["number"],
        ):
            index[group] = issue
    return index


def _meets_thresholds(occurrences: int, affected_requests: int) -> bool:
    return (
        occurrences >= MIN_PRODUCTION_OCCURRENCES
        and affected_requests >= MIN_PRODUCTION_REQUESTS
    )


def _issue_labels(group: ErrorGroup) -> list[str]:
    service_label = f"{SERVICE_LABEL_PREFIX}{group.family}"
    if len(service_label) > MAX_LABEL_LENGTH:
        return [BASE_LABEL]
    return [BASE_LABEL, service_label]


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class IssueSynchronizer:
    """Creates and updates one issue per production error group."""

    def __init__(
        self,
        github: GitHubClient,
        window: ReportingWindow,
        project_id: str,
        *,
        dry_run: bool,
    ) -> None:
        """Sync the groups of ``window``; a dry run reads but never writes."""
        self._github = github
        self._window = window
        self._project_id = project_id
        self._dry_run = dry_run
        self._known_labels: set[str] | None = None

    def run(self, groups: Iterable[ErrorGroup]) -> SyncResult:
        """Sync each group, opening at most five issues, largest groups first."""
        issues = _issues_by_fingerprint(self._github.list_issues(BOT_LOGIN))
        actions: list[SyncAction] = []
        opened = 0
        for group in groups:
            issue = issues.get(group.fingerprint)
            number: int | None = None
            if issue is not None:
                number = issue["number"]
                action = self._update(group, issue)
            elif not _meets_thresholds(
                group.production.occurrences, group.production.affected_requests
            ):
                action = "below-threshold"
            elif opened >= MAX_NEW_ISSUES_PER_RUN:
                action = "deferred"
            else:
                number = self._open(group)
                opened += 1
                action = "created"
            actions.append(
                SyncAction(
                    fingerprint=group.fingerprint,
                    kind=group.kind,
                    family=group.family,
                    production_occurrences=group.production.occurrences,
                    staging_occurrences=group.staging.occurrences,
                    issue_number=number,
                    action=action,
                )
            )
        deferred = sum(action.action == "deferred" for action in actions)
        return SyncResult(actions, deferred)

    def _ensure_labels(self, names: Iterable[str]) -> None:
        if self._known_labels is None:
            self._known_labels = self._github.list_labels()
        for name in names:
            if name not in self._known_labels:
                color, description = LABEL_DETAILS.get(name, SERVICE_LABEL_DETAILS)
                self._github.create_label(name, color, description)
                self._known_labels.add(name)

    def _open(self, group: ErrorGroup) -> int | None:
        if self._dry_run:
            return None
        labels = _issue_labels(group)
        self._ensure_labels(labels)
        issue = self._github.create_issue(
            issue_title(group),
            issue_body(group, self._window, self._project_id),
            labels,
        )
        number = issue["number"]
        applied = {label["name"] for label in issue.get("labels", [])}
        missing = [label for label in labels if label not in applied]
        if missing and not set(missing) <= self._github.add_labels(number, missing):
            msg = f"GitHub did not apply the labels to issue #{number}"
            raise GitHubLabelError(msg)
        return number

    def _reopen_since(self, issue: Mapping[str, Any]) -> datetime | None:
        """Return when regressions count from, if the issue should reopen."""
        if issue.get("state") != "closed":
            return None
        if issue.get("state_reason") not in REOPENABLE_CLOSE_REASONS:
            return None
        closed_at = _parse_time(issue.get("closed_at"))
        return None if closed_at is None else closed_at + REOPEN_DELAY

    def _update(self, group: ErrorGroup, issue: Mapping[str, Any]) -> str:
        body = issue.get("body") or ""
        state = parse_state(body)
        reported_end = _parse_time(state.get("window_end")) if state else None
        if reported_end is not None and reported_end > self._window.end:
            return "kept-newer"
        new_body = replace_section(
            body, issue_section(group, self._window, self._project_id)
        )
        since = self._reopen_since(issue)
        if since is not None and _meets_thresholds(*group.production_since(since)):
            if not self._dry_run:
                self._reopen(issue["number"], new_body, group, since)
            return "reopened"
        if new_body == body:
            return "unchanged"
        if not self._dry_run:
            self._github.update_issue(issue["number"], {"body": new_body})
        return "updated"

    def _reopen(
        self, number: int, body: str, group: ErrorGroup, since: datetime
    ) -> None:
        occurrences, affected_requests = group.production_since(since)
        self._ensure_labels([REGRESSION_LABEL])
        self._github.update_issue(
            number, {"body": body, "state": "open", "state_reason": "reopened"}
        )
        self._github.add_labels(number, [REGRESSION_LABEL])
        self._github.add_comment(
            number,
            "Production failures returned after this issue was closed: "
            f"{occurrences:,} occurrences in {affected_requests:,} requests since "
            f"{_eastern_time(since)}, 24 hours after it was closed.",
        )


def sync_issues(
    groups: Iterable[ErrorGroup],
    window: ReportingWindow,
    project_id: str,
    github: GitHubClient,
    *,
    dry_run: bool,
) -> SyncResult:
    """Create or update the issue for each group; a dry run makes no changes."""
    synchronizer = IssueSynchronizer(github, window, project_id, dry_run=dry_run)
    return synchronizer.run(groups)


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
    bigquery_transport: Callable[[HttpRequest], HttpResponse] = urllib_transport
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
    summary_path: str | None


def read_settings(environ: Mapping[str, str]) -> Settings:
    """Read and check the environment variables the run needs."""
    missing = [name for name in REQUIRED_ENVIRONMENT_VARIABLES if not environ.get(name)]
    if missing:
        msg = f"missing environment variables: {', '.join(missing)}"
        raise ConfigurationError(msg)
    if not REPOSITORY_PATTERN.match(environ["GITHUB_REPOSITORY"]):
        msg = "GITHUB_REPOSITORY must be owner/name"
        raise ConfigurationError(msg)
    try:
        key = fingerprint_key(environ["TELEMETRY_ERROR_FINGERPRINT_KEY"])
    except ValueError as error:
        raise ConfigurationError(str(error)) from None
    return Settings(
        google_access_token=environ["GOOGLE_OAUTH_ACCESS_TOKEN"],
        github_credential=environ["GITHUB_TOKEN"],
        repository=environ["GITHUB_REPOSITORY"],
        fingerprint_key=key,
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
        f"Window: {_window_text(window)}.",
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
            f"| {_code(action.fingerprint)} | {action.kind} | {_code(action.family)} "
            f"| {action.production_occurrences:,} | {action.staging_occurrences:,} "
            f"| {issue} | {action.action} |"
        )
    return "\n".join(lines)


def _append_summary(path: str, summary: str) -> None:
    with Path(path).open("a", encoding="utf-8") as summary_file:
        summary_file.write(f"{summary}\n")


def _report(arguments: argparse.Namespace, runtime: Runtime) -> str:
    settings = _stage("configuration", lambda: read_settings(runtime.environ))
    window = _stage(
        "configuration", lambda: _report_window(arguments.report_date, runtime.now())
    )
    bigquery = BigQueryClient(
        arguments.project_id, settings.google_access_token, runtime.bigquery_transport
    )
    records = _stage(
        "query error records", lambda: fetch_error_records(bigquery, window)
    )
    request_counts = _stage(
        "query request counts", lambda: fetch_request_counts(bigquery, window)
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
            groups, window, arguments.project_id, github, dry_run=arguments.dry_run
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


if __name__ == "__main__":
    raise SystemExit(main())
