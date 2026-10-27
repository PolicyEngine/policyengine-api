"""Tests for telemetry_error_issues.groups: grouping failures and their measures."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from telemetry_error_issues.groups import build_groups
from telemetry_error_issues.records import fingerprint
from telemetry_error_issues.window import reporting_window

from tests.unit.telemetry_error_issues.report_support import (
    FINGERPRINT_KEY,
    REPORT_DATE,
    WINDOW_NOON,
    exception_record,
    failed_request_record,
    failures_with_and_without_a_route,
    hours_after_window_noon,
    message_record,
    request_count,
)


def _only_group(records: list, request_counts=()) -> object:
    groups = build_groups(
        records,
        list(request_counts),
        reporting_window(REPORT_DATE),
        FINGERPRINT_KEY,
    )
    assert len(groups) == 1
    return groups[0]


def test_measures_count_occurrences_requests_and_observability_ids() -> None:
    records = [
        exception_record(request_key="r1", observability_key="o1"),
        exception_record(
            request_key="r2",
            observability_key="o1",
            timestamp=hours_after_window_noon(1),
        ),
        exception_record(
            request_key="r3",
            observability_key="o2",
            timestamp=hours_after_window_noon(2),
        ),
        exception_record(
            request_key="s1",
            environment_name="staging",
            timestamp=hours_after_window_noon(3),
        ),
    ]

    group = _only_group(records)

    assert group.production.occurrences == 3
    assert group.production.affected_requests == 3
    assert group.production.observability_ids == 2
    assert group.staging.occurrences == 1
    assert group.staging.affected_requests == 1
    assert group.staging.observability_ids == 0


def test_measures_affected_requests_fall_back_to_observability_id_then_trace() -> None:
    records = [
        exception_record(request_key=None, trace_key=None, observability_key="o1"),
        exception_record(
            request_key=None,
            trace_key=None,
            observability_key="o1",
            timestamp=hours_after_window_noon(1),
        ),
        exception_record(request_key=None, trace_key="t1"),
        exception_record(request_key=None, trace_key=None),
        exception_record(
            request_key=None, trace_key=None, timestamp=hours_after_window_noon(2)
        ),
    ]

    group = _only_group(records)

    assert group.production.occurrences == 5
    # o1 once, t1 once, and each record without any identifier on its own.
    assert group.production.affected_requests == 4


def test_measures_error_rate_uses_requests_to_the_affected_routes() -> None:
    records = [
        exception_record(request_key="r1", route="/<country_id>/report"),
        exception_record(
            request_key="r2",
            route="/<country_id>/calculate",
            timestamp=hours_after_window_noon(1),
        ),
        exception_record(
            request_key="r3",
            route="/<country_id>/calculate",
            timestamp=hours_after_window_noon(2),
        ),
    ]
    request_counts = [
        request_count("/<country_id>/report", 200),
        request_count("/<country_id>/calculate", 100),
        request_count("/<country_id>/metadata", 5000),
        request_count("/<country_id>/report", 10, environment_name="staging"),
        request_count(
            "/<country_id>/report",
            7000,
            service_name="policyengine-simulation-entry",
        ),
    ]

    group = _only_group(records, request_counts)

    assert group.production.route_requests == 300
    assert group.production.error_rate == pytest.approx(0.01)
    assert group.staging.error_rate is None


def test_measures_error_rate_counts_only_failures_on_routes() -> None:
    group = _only_group(
        failures_with_and_without_a_route(),
        [request_count("/<country_id>/calculate", 1)],
    )

    assert group.production.affected_requests == 3
    assert group.production.route_affected_requests == 1
    assert group.production.route_requests == 1
    assert group.production.error_rate == pytest.approx(1.0)


def test_measures_error_rate_counts_every_simulation_service_version() -> None:
    records = [
        failed_request_record(
            service_name="policyengine-simulation-py1-2-3",
            route="/jobs/{job_id}",
        )
    ]
    request_counts = [
        request_count(
            "/jobs/{job_id}",
            30,
            service_name="policyengine-simulation-py1-2-3",
        ),
        request_count(
            "/jobs/{job_id}",
            70,
            service_name="policyengine-simulation-py1-2-4",
        ),
    ]

    group = _only_group(records, request_counts)

    assert group.production.route_requests == 100
    assert group.production.error_rate == pytest.approx(0.01)


def test_measures_error_rate_is_unknown_without_route_requests() -> None:
    group = _only_group([message_record(route=None, operation_name="sync")])

    assert group.production.route_requests == 0
    assert group.production.error_rate is None


def test_measures_hourly_rates_for_the_window_and_the_previous_seven_days() -> None:
    window_records = [
        message_record(
            request_key=f"w{index}", timestamp=hours_after_window_noon(index)
        )
        for index in range(6)
    ]
    previous_records = [
        message_record(
            request_key=f"p{index}", timestamp=hours_after_window_noon(-13 - 4 * index)
        )
        for index in range(42)
    ]

    group = _only_group(window_records + previous_records)

    assert group.production.occurrences == 6
    assert group.production.hourly_rate == pytest.approx(6 / 24)
    assert group.production.previous_hourly_rate == pytest.approx(42 / 168)


def test_measures_hourly_rate_uses_the_25_hour_fall_back_day() -> None:
    fall_back_noon = datetime(2026, 11, 1, 17, 0, tzinfo=UTC)
    records = [
        message_record(
            request_key=f"w{index}",
            timestamp=fall_back_noon + timedelta(hours=index),
        )
        for index in range(5)
    ]

    groups = build_groups(
        records, [], reporting_window(date(2026, 11, 1)), FINGERPRINT_KEY
    )

    assert groups[0].production.hourly_rate == pytest.approx(5 / 25)


def test_measures_first_and_last_seen_cover_the_queried_eight_days() -> None:
    records = [
        message_record(request_key="early", timestamp=hours_after_window_noon(-24 * 6)),
        message_record(request_key="latest", timestamp=hours_after_window_noon(5)),
        message_record(request_key="middle", timestamp=hours_after_window_noon(1)),
    ]

    group = _only_group(records)

    assert group.production.first_seen == hours_after_window_noon(-24 * 6)
    assert group.production.last_seen == hours_after_window_noon(5)
    assert group.staging.first_seen is None
    assert group.staging.last_seen is None


def test_measures_ignore_records_outside_the_queried_days() -> None:
    records = [
        message_record(request_key="in-window"),
        message_record(
            request_key="too-old", timestamp=hours_after_window_noon(-24 * 9)
        ),
        message_record(request_key="too-new", timestamp=hours_after_window_noon(24)),
    ]

    group = _only_group(records)

    assert group.production.occurrences == 1
    assert group.production.first_seen == WINDOW_NOON


def test_measures_report_only_groups_seen_in_the_window() -> None:
    records = [
        message_record(request_key="today"),
        message_record(
            request_key="last-week",
            message_template="something else",
            timestamp=hours_after_window_noon(-48),
        ),
    ]

    groups = build_groups(records, [], reporting_window(REPORT_DATE), FINGERPRINT_KEY)

    assert [group.fingerprint for group in groups] == [
        fingerprint(records[0], FINGERPRINT_KEY)
    ]


def test_measures_ignore_environments_other_than_production_and_staging() -> None:
    records = [
        message_record(environment_name="local"),
        message_record(environment_name=None, request_key="r2"),
    ]

    groups = build_groups(records, [], reporting_window(REPORT_DATE), FINGERPRINT_KEY)

    assert groups == []


def test_measures_describe_the_group_with_its_most_frequent_production_route() -> None:
    records = [
        exception_record(request_key="r1", route="/<country_id>/report"),
        exception_record(request_key="r2", route="/<country_id>/calculate"),
        exception_record(request_key="r3", route="/<country_id>/calculate"),
        exception_record(
            request_key="s1",
            route="/<country_id>/report",
            environment_name="staging",
        ),
        exception_record(
            request_key="s2",
            route="/<country_id>/report",
            environment_name="staging",
        ),
    ]

    group = _only_group(records)

    assert group.kind == "exception"
    assert group.family == "policyengine-api"
    assert group.error_type == "StaleDataError"
    assert group.route == "/<country_id>/calculate"


def test_measures_describe_groups_only_with_validated_values() -> None:
    group = _only_group(
        [
            exception_record(
                error_type="SENTINEL not a class",
                route="/us/policy/12345",
            )
        ],
    )

    assert group.error_type == "<unrecognized>"
    assert group.route == "<unrecognized>"


def test_measures_list_up_to_three_related_fingerprints_by_shared_traces() -> None:
    base = exception_record(request_key="r1", trace_key="t1")
    base_second = exception_record(
        request_key="r2", trace_key="t2", timestamp=hours_after_window_noon(1)
    )
    related_twice = [
        message_record(
            service_name="policyengine-simulation-entry",
            request_key=f"x{index}",
            trace_key=trace,
        )
        for index, trace in enumerate(("t1", "t2"))
    ]
    related_once = [
        message_record(
            service_name="policyengine-simulation-gateway",
            request_key=f"y{index}",
            trace_key="t1",
            message_template=template,
        )
        for index, template in enumerate(("first error", "second error", "third"))
    ]

    groups = build_groups(
        [base, base_second, *related_twice, *related_once],
        [],
        reporting_window(REPORT_DATE),
        FINGERPRINT_KEY,
    )
    by_fingerprint = {group.fingerprint: group for group in groups}
    base_group = by_fingerprint[fingerprint(base, FINGERPRINT_KEY)]
    twice = fingerprint(related_twice[0], FINGERPRINT_KEY)
    once = sorted(fingerprint(record, FINGERPRINT_KEY) for record in related_once)

    assert base_group.related_fingerprints == (twice, once[0], once[1])


def test_measures_sort_groups_by_production_occurrences() -> None:
    frequent = [
        message_record(request_key=f"f{index}", message_template="often")
        for index in range(3)
    ]
    staging_only = [
        message_record(
            request_key=f"s{index}",
            message_template="staging",
            environment_name="staging",
        )
        for index in range(5)
    ]
    rare = [message_record(request_key="rare", message_template="rare")]

    groups = build_groups(
        staging_only + rare + frequent,
        [],
        reporting_window(REPORT_DATE),
        FINGERPRINT_KEY,
    )

    assert [group.production.occurrences for group in groups] == [3, 1, 0]


def test_measures_count_production_occurrences_since_a_moment() -> None:
    records = [
        exception_record(request_key="before", timestamp=hours_after_window_noon(-30)),
        exception_record(request_key="r1", timestamp=hours_after_window_noon(1)),
        exception_record(request_key="r2", timestamp=hours_after_window_noon(2)),
        exception_record(
            request_key="r2", trace_key="t9", timestamp=hours_after_window_noon(3)
        ),
        exception_record(request_key="staging", environment_name="staging"),
    ]

    group = _only_group(records)

    assert group.production_since(hours_after_window_noon(-1)) == (2, 2)
    assert group.production_since(hours_after_window_noon(-48)) == (3, 3)
