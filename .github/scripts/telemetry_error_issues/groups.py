"""Group failures by fingerprint, and measure each group in each environment."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from telemetry_error_issues.normalization import (
    environment_class,
    is_route_template,
    public_error_type,
    public_family,
    public_operation,
    public_route,
    public_status,
    service_family,
)
from telemetry_error_issues.records import ErrorRecord, fingerprint, primary_records

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from telemetry_error_issues.window import ReportingWindow

REPORTED_ENVIRONMENTS = ("production", "staging")
MAX_RELATED_FINGERPRINTS = 3


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


def _error_rate(affected_requests: int, completed_requests: int) -> float | None:
    """Return the share of completed requests that failed, or None.

    There is no share without completed requests, or when more requests failed
    than were logged as completed, which means completion records are missing.
    """
    if completed_requests == 0 or affected_requests > completed_requests:
        return None
    return affected_requests / completed_requests


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
    # same route templates. Failures without a route, such as background
    # operations, and failures on a placeholder route, such as "<unmatched>",
    # are left out of both.
    on_routes = [item for item in in_window if is_route_template(item.route)]
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
        error_rate=_error_rate(route_affected_requests, requests),
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
