"""Tests for telemetry_error_issues.window: the reporting window."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from telemetry_error_issues.window import default_report_date, reporting_window

from tests.unit.telemetry_error_issues.report_support import EASTERN


@pytest.mark.parametrize(
    "run_time",
    [
        datetime(2026, 10, 21, 0, 45, tzinfo=EASTERN),
        datetime(2026, 10, 21, 3, 30, tzinfo=EASTERN),
        datetime(2026, 10, 21, 4, 45, tzinfo=UTC),
    ],
)
def test_window_scheduled_run_reports_the_previous_eastern_day(
    run_time: datetime,
) -> None:
    window = reporting_window(default_report_date(run_time))

    assert window.start == datetime(2026, 10, 20, 0, 0, tzinfo=EASTERN)
    assert window.end == datetime(2026, 10, 21, 0, 0, tzinfo=EASTERN)
    assert window.hours == 24


def test_window_default_date_follows_eastern_time_not_utc() -> None:
    # 02:00 UTC on 21 October is still 22:00 on 20 October in New York.
    run_time = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)

    assert default_report_date(run_time) == date(2026, 10, 19)


def test_window_spring_forward_day_lasts_23_hours() -> None:
    window = reporting_window(date(2026, 3, 8))

    assert window.start.utcoffset() == timedelta(hours=-5)
    assert window.end.utcoffset() == timedelta(hours=-4)
    assert window.hours == 23


def test_window_fall_back_day_lasts_25_hours() -> None:
    window = reporting_window(date(2026, 11, 1))

    assert window.start.utcoffset() == timedelta(hours=-4)
    assert window.end.utcoffset() == timedelta(hours=-5)
    assert window.hours == 25


def test_window_bounds_convert_to_utc_for_queries() -> None:
    window = reporting_window(date(2026, 11, 1))

    assert window.start.astimezone(UTC) == datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
    assert window.end.astimezone(UTC) == datetime(2026, 11, 2, 5, 0, tzinfo=UTC)
