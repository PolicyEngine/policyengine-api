"""Tests for telemetry_error_issues.cli: the command-line arguments."""

from __future__ import annotations

from datetime import date

import pytest
from telemetry_error_issues.cli import main, parse_arguments


def test_cli_parses_project_dry_run_and_report_date() -> None:
    arguments = parse_arguments(
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


def test_cli_defaults_to_a_live_run_of_the_previous_day() -> None:
    arguments = parse_arguments(["--project-id", "policyengine-observability"])

    assert arguments.dry_run is False
    assert arguments.report_date is None


def test_cli_treats_an_empty_report_date_as_unset() -> None:
    arguments = parse_arguments(
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
    argv: list[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(argv)

    assert raised.value.code == 2
