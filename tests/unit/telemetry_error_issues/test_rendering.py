"""Tests for telemetry_error_issues.rendering: issue titles and bodies."""

from __future__ import annotations

from urllib.parse import quote, unquote, urlparse, urlsplit

import pytest
from telemetry_error_issues.bigquery import error_record_from_row
from telemetry_error_issues.groups import build_groups
from telemetry_error_issues.rendering import (
    SECTION_END,
    SECTION_START,
    issue_body,
    issue_title,
    logs_explorer_url,
    parse_state,
)
from telemetry_error_issues.window import reporting_window

from tests.unit.telemetry_error_issues.report_support import (
    FINGERPRINT_KEY,
    GATEWAY_SERVICE,
    LOG_SOURCE,
    REPORT_DATE,
    exception_record,
    failed_request_record,
    failures_on_the_unmatched_route,
    failures_with_and_without_a_route,
    hours_after_window_noon,
    message_record,
    request_count,
    sentinel_row,
)


def _group(records: list, request_counts=()) -> object:
    groups = build_groups(
        records,
        list(request_counts),
        reporting_window(REPORT_DATE),
        FINGERPRINT_KEY,
    )
    return groups[0]


def _render(group: object) -> tuple[str, str]:
    window = reporting_window(REPORT_DATE)
    return (
        issue_title(group),
        issue_body(group, window, LOG_SOURCE),
    )


def _section(body: str) -> str:
    start = body.index(SECTION_START)
    end = body.index(SECTION_END) + len(SECTION_END)
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


def test_render_title_names_the_exception_and_its_most_frequent_route() -> None:
    group = _group([exception_record()])

    title, _ = _render(group)

    assert title == (
        "[telemetry] policyengine-api: StaleDataError on `/<country_id>/report` "
        f"({group.fingerprint})"
    )


def test_render_title_for_a_logged_error() -> None:
    route_group = _group([message_record()])
    operation_group = _group(
        [message_record(route=None, operation_name="simulation.dispatch")],
    )

    assert issue_title(route_group).startswith(
        "[telemetry] policyengine-api: logged error on `/<country_id>/report` ("
    )
    assert issue_title(operation_group).startswith(
        "[telemetry] policyengine-api: logged error in `simulation.dispatch` ("
    )


def test_render_title_for_a_failed_request_without_an_exception() -> None:
    group = _group([failed_request_record(status_code=502)])

    assert issue_title(group) == (
        "[telemetry] policyengine-api: HTTP 502 without recorded exception on "
        f"`/<country_id>/report` ({group.fingerprint})"
    )


def test_render_title_without_a_route() -> None:
    group = _group(
        [
            exception_record(
                service_name="policyengine-stage12-us-worker",
                route=None,
            )
        ],
    )

    assert issue_title(group) == (
        "[telemetry] policyengine-stage12-us-worker: StaleDataError "
        f"({group.fingerprint})"
    )


def test_render_body_marked_section_holds_the_measures_table() -> None:
    records = [
        exception_record(request_key="r1", observability_key="o1"),
        exception_record(request_key="r2", timestamp=hours_after_window_noon(2)),
        exception_record(
            request_key="s1",
            environment_name="staging",
            timestamp=hours_after_window_noon(1),
        ),
    ]
    group = _group(
        records,
        [request_count("/<country_id>/report", 400)],
    )

    _, body = _render(group)
    section = _section(body)

    assert body.index(SECTION_START) > 0
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


def test_render_error_rate_names_only_failures_on_routes() -> None:
    group = _group(
        failures_with_and_without_a_route(),
        [request_count("/<country_id>/calculate", 1)],
    )

    _, body = _render(group)

    assert "| Error rate on affected routes | 100.00% (1 of 1 requests) | n/a |" in body


def test_render_error_rate_is_unavailable_for_failures_on_the_unmatched_route() -> None:
    group = _group(
        failures_on_the_unmatched_route(),
        [request_count("<unmatched>", 1, service_name=GATEWAY_SERVICE)],
    )

    _, body = _render(group)

    assert "| Error rate on affected routes | n/a | n/a |" in body
    assert "- Most frequent route: `<unmatched>`" in body


def test_render_error_rate_explains_failures_outnumbering_completions() -> None:
    records = [
        exception_record(
            request_key=f"r{index}",
            route="/<country_id>/calculate",
            timestamp=hours_after_window_noon(index),
        )
        for index in range(3)
    ]
    group = _group(records, [request_count("/<country_id>/calculate", 2)])

    _, body = _render(group)

    assert (
        "| Error rate on affected routes "
        "| n/a (3 affected requests, only 2 logged as completed) | n/a |" in body
    )


def test_render_body_lists_related_fingerprints() -> None:
    records = [
        exception_record(trace_key="t1"),
        message_record(service_name="policyengine-simulation-entry", trace_key="t1"),
    ]
    groups = build_groups(records, [], reporting_window(REPORT_DATE), FINGERPRINT_KEY)
    exception_group = next(group for group in groups if group.kind == "exception")
    other = exception_group.related_fingerprints[0]

    _, body = _render(exception_group)

    assert f"Related fingerprints (sharing traces): `{other}`" in body


def test_render_body_state_comment_records_the_group_and_window() -> None:
    group = _group([exception_record()])

    _, body = _render(group)

    assert parse_state(body) == {
        "algorithm": 1,
        "fingerprint": group.fingerprint,
        "kind": "exception",
        "window_end": "2026-10-21T04:00:00+00:00",
    }


def test_render_body_stays_under_the_github_limit() -> None:
    # The longest route that still passes validation (195 characters).
    long_route = "/" + "/".join(["<segment_name>"] * 13)
    records = [
        exception_record(
            error_type="E" * 120,
            route=long_route,
            trace_key=f"t{index}",
            request_key=f"r{index}",
        )
        for index in range(4)
    ]
    records += [
        message_record(
            request_key=f"m{index}",
            trace_key=f"t{index}",
            message_template=f"template {index}",
            service_name="policyengine-simulation-entry",
        )
        for index in range(4)
    ]
    groups = build_groups(records, [], reporting_window(REPORT_DATE), FINGERPRINT_KEY)

    for group in groups:
        title, body = _render(group)
        assert len(body) < 65_536
        assert len(title) <= 256


def test_render_logs_link_filters_exceptions_by_service_and_type() -> None:
    group = _group([exception_record()])
    url = logs_explorer_url(group, reporting_window(REPORT_DATE), LOG_SOURCE)

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


def test_render_logs_link_names_the_configured_bucket_location_and_view() -> None:
    group = _group([exception_record()])
    log_source = LOG_SOURCE._replace(
        project_id="other-project",
        bucket="central-logs",
        bucket_location="us-central1",
        view="_Requests",
    )

    url = logs_explorer_url(group, reporting_window(REPORT_DATE), log_source)

    _, settings = _logs_query(url)
    assert urlparse(url).query == "project=other-project"
    assert settings["storageScope"] == quote(
        "storage,projects/other-project/locations/us-central1/"
        "buckets/central-logs/views/_Requests",
        safe="",
    )


@pytest.mark.parametrize(
    "unsafe_names",
    [
        {"project_id": "SENTINEL project"},
        {"bucket": "logs/views/other"},
        {"bucket_location": "global/../other"},
        {"view": "_AllLogs?project=other"},
    ],
)
def test_render_logs_link_refuses_names_that_are_not_identifiers(
    unsafe_names: dict[str, str],
) -> None:
    group = _group([exception_record()])

    with pytest.raises(ValueError, match="is not a valid name"):
        logs_explorer_url(
            group, reporting_window(REPORT_DATE), LOG_SOURCE._replace(**unsafe_names)
        )


def test_render_logs_link_filters_failed_requests_by_route_and_status() -> None:
    group = _group(
        [
            failed_request_record(
                service_name="policyengine-simulation-py1-2-3",
                route="/jobs/{job_id}",
                status_code=504,
            )
        ],
    )

    query, _ = _logs_query(
        logs_explorer_url(group, reporting_window(REPORT_DATE), LOG_SOURCE)
    )

    assert query.splitlines()[1:5] == [
        'jsonPayload."service.name"=~"^policyengine-simulation-py[0-9]+-[0-9]+-[0-9]+$"',
        'jsonPayload."event.name"="request.completed"',
        'jsonPayload."http.route"="/jobs/{job_id}"',
        'jsonPayload."http.response.status_code"=504',
    ]


def test_render_logs_link_filters_logged_errors_by_route_or_operation() -> None:
    window = reporting_window(REPORT_DATE)
    route_group = _group([message_record()])
    operation_group = _group(
        [message_record(route=None, operation_name="simulation.dispatch")],
    )

    route_query, _ = _logs_query(logs_explorer_url(route_group, window, LOG_SOURCE))
    operation_query, _ = _logs_query(
        logs_explorer_url(operation_group, window, LOG_SOURCE)
    )

    assert 'jsonPayload."http.route"="/<country_id>/report"' in route_query
    assert "severity>=ERROR" in route_query
    assert 'jsonPayload."operation.name"="simulation.dispatch"' in operation_query


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
    overrides: dict[str, object],
) -> None:
    record = error_record_from_row(sentinel_row(**overrides))
    group = _group([record])
    window = reporting_window(REPORT_DATE)

    title, body = _render(group)
    url = logs_explorer_url(group, window, LOG_SOURCE)

    for output in (title, body, url, unquote(url)):
        assert "SENTINEL" not in output
