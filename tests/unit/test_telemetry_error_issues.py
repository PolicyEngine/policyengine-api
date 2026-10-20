"""Tests for .github/scripts/sync_telemetry_error_issues.py."""

from __future__ import annotations

import functools
import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest

if TYPE_CHECKING:
    from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO / ".github" / "scripts" / "sync_telemetry_error_issues.py"
EASTERN = ZoneInfo("America/New_York")


@functools.cache
def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sync_telemetry_error_issues", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_script() -> ModuleType:
    return _load_script()


# Reporting window and command-line interface


@pytest.mark.parametrize(
    "run_time",
    [
        datetime(2026, 10, 21, 0, 45, tzinfo=EASTERN),
        datetime(2026, 10, 21, 3, 30, tzinfo=EASTERN),
        datetime(2026, 10, 21, 4, 45, tzinfo=UTC),
    ],
)
def test_window_scheduled_run_reports_the_previous_eastern_day(
    sync_script: ModuleType, run_time: datetime
) -> None:
    window = sync_script.reporting_window(sync_script.default_report_date(run_time))

    assert window.start == datetime(2026, 10, 20, 0, 0, tzinfo=EASTERN)
    assert window.end == datetime(2026, 10, 21, 0, 0, tzinfo=EASTERN)
    assert window.hours == 24


def test_window_default_date_follows_eastern_time_not_utc(
    sync_script: ModuleType,
) -> None:
    # 02:00 UTC on 21 October is still 22:00 on 20 October in New York.
    run_time = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)

    assert sync_script.default_report_date(run_time) == date(2026, 10, 19)


def test_window_spring_forward_day_lasts_23_hours(sync_script: ModuleType) -> None:
    window = sync_script.reporting_window(date(2026, 3, 8))

    assert window.start.utcoffset() == timedelta(hours=-5)
    assert window.end.utcoffset() == timedelta(hours=-4)
    assert window.hours == 23


def test_window_fall_back_day_lasts_25_hours(sync_script: ModuleType) -> None:
    window = sync_script.reporting_window(date(2026, 11, 1))

    assert window.start.utcoffset() == timedelta(hours=-4)
    assert window.end.utcoffset() == timedelta(hours=-5)
    assert window.hours == 25


def test_window_bounds_convert_to_utc_for_queries(sync_script: ModuleType) -> None:
    window = sync_script.reporting_window(date(2026, 11, 1))

    assert window.start.astimezone(UTC) == datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
    assert window.end.astimezone(UTC) == datetime(2026, 11, 2, 5, 0, tzinfo=UTC)


def test_cli_parses_project_dry_run_and_report_date(sync_script: ModuleType) -> None:
    arguments = sync_script.parse_arguments(
        [
            "--project-id",
            "policyengine-observability",
            "--dry-run",
            "--report-date",
            "2026-10-19",
        ]
    )

    assert arguments.project_id == "policyengine-observability"
    assert arguments.dry_run is True
    assert arguments.report_date == date(2026, 10, 19)


def test_cli_defaults_to_a_live_run_of_the_previous_day(
    sync_script: ModuleType,
) -> None:
    arguments = sync_script.parse_arguments(
        ["--project-id", "policyengine-observability"]
    )

    assert arguments.dry_run is False
    assert arguments.report_date is None


def test_cli_treats_an_empty_report_date_as_unset(sync_script: ModuleType) -> None:
    arguments = sync_script.parse_arguments(
        ["--project-id", "policyengine-observability", "--report-date", ""]
    )

    assert arguments.report_date is None


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--dry-run"],
        ["--project-id", "policyengine-observability", "--report-date", "20 Oct"],
    ],
)
def test_cli_rejects_missing_project_or_invalid_date_with_exit_code_2(
    sync_script: ModuleType, argv: list[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        sync_script.main(argv)

    assert raised.value.code == 2
