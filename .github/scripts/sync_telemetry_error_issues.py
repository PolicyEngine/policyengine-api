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
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, NamedTuple
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from collections.abc import Iterable

REPORTING_TIME_ZONE = ZoneInfo("America/New_York")

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
FRAME_PARTS = re.compile(r'^(?P<path>[^"\n]+)", line [0-9]+, in (?P<function>\S+)$')
FINGERPRINT_FRAME_COUNT = 3
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
        start=datetime.combine(report_date, time(0), tzinfo=REPORTING_TIME_ZONE),
        end=datetime.combine(next_date, time(0), tzinfo=REPORTING_TIME_ZONE),
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

    These are the three innermost frames in application packages. Without
    application frames they are the three innermost frames of any kind, and
    without a stack, a placeholder.
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
    routes = {item.route for item in in_window if item.route}
    requests = route_requests.total(family, environment, routes)
    timestamps = [item.timestamp for item in in_environment]
    return EnvironmentMeasures(
        occurrences=len(in_window),
        affected_requests=affected_requests,
        observability_ids=len(
            {item.observability_key for item in in_window if item.observability_key}
        ),
        route_requests=requests,
        error_rate=affected_requests / requests if requests else None,
        hourly_rate=len(in_window) / window.hours,
        previous_hourly_rate=before_window / window.lookback_hours,
        first_seen=min(timestamps, default=None),
        last_seen=max(timestamps, default=None),
    )


def _most_frequent_route(occurrences: list[Occurrence], window: ReportingWindow) -> str:
    """Return the route most failures in the window used, preferring production."""
    in_window = [item for item in occurrences if item.timestamp >= window.start]
    production = [item for item in in_window if item.environment == "production"]
    routes = Counter(item.route or MISSING for item in production or in_window)
    route, _ = min(routes.items(), key=lambda item: (-item[1], item[0]))
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


def main(argv: list[str] | None = None) -> int:
    """Run one report and return the process exit code."""
    parse_arguments(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
