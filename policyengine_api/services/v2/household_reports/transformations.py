"""Conversions between household report inputs and records."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from policyengine_api.services.v2.household_reports.types import (
    HouseholdReportSubmission,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from uuid import UUID

    from policyengine_api.services.v2.household_reports.types import (
        HouseholdReportFields,
        HouseholdReportRecord,
    )


def household_report_submission(
    report_input: HouseholdReportFields,
    *,
    country_id: str,
    policyengine_version: str,
) -> HouseholdReportSubmission:
    """Return what the Simulation Entrypoint is asked to create."""
    return HouseholdReportSubmission(
        country_id=country_id,
        policyengine_version=policyengine_version,
        household_id=report_input.household_id,
        baseline=report_input.baseline,
        reform=report_input.reform,
    )


def run_catalog_version_ids(reports: Iterable[HouseholdReportRecord]) -> set[UUID]:
    """Return the catalog versions the reports' runs ran on."""
    return {
        report.run.tax_benefit_model_version_id
        for report in reports
        if report.run is not None
    }


def with_policyengine_version(
    report: HouseholdReportRecord, policyengine_versions: Mapping[UUID, str]
) -> HouseholdReportRecord:
    """Name the PolicyEngine.py version of the report's run's catalog version."""
    if report.run is None:
        return report
    return replace(
        report,
        run=replace(
            report.run,
            policyengine_version=policyengine_versions.get(
                report.run.tax_benefit_model_version_id
            ),
        ),
    )
