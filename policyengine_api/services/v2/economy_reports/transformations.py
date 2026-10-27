"""Pure representation transformations for v2 economy report operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.economy_reports.types import EconomyReportSubmission

if TYPE_CHECKING:
    from policyengine_api.services.v2.economy_reports.types import EconomyReportFields


def economy_report_submission(
    report_input: EconomyReportFields,
    *,
    country_id: str,
    policyengine_version: str,
) -> EconomyReportSubmission:
    """Build the entrypoint request for a new report on one catalog version."""
    return EconomyReportSubmission(
        country_id=country_id,
        policyengine_version=policyengine_version,
        year=report_input.year,
        region_code=report_input.region_code,
        dataset_name=report_input.dataset_name,
        baseline=report_input.baseline,
        reform=report_input.reform,
    )
