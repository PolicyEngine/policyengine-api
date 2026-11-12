"""Read a failed household report run's failure documents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from policyengine_api.services.v2.household_calculations.types import (
    StoredExecutionFailure,
)
from policyengine_api.services.v2.stored_reports.household_results.types import (
    HouseholdReportFailure,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import ReportRun
    from policyengine_api.services.v2.household_calculations.types import (
        HouseholdCalculationFailure,
    )
    from policyengine_api.services.v2.stored_reports.household_results.types import (
        HouseholdResultRows,
    )


def _side_failure(
    rows: HouseholdResultRows, simulation_run_id: UUID | None
) -> HouseholdCalculationFailure | None:
    """Return the side's failure, or None without a readable failure document."""
    if simulation_run_id is None:
        return None
    try:
        document = StoredExecutionFailure.model_validate(
            rows.documents.get(simulation_run_id)
        )
    except ValidationError:
        return None
    return document.calculation_failure()


def household_report_failure(
    report_run: ReportRun, rows: HouseholdResultRows
) -> HouseholdReportFailure:
    """Return why each side of a failed report run failed, where it says.

    A side with no failure document, or one that cannot be read, gives None:
    a failure is never made unreadable by its document.
    """
    return HouseholdReportFailure(
        baseline=_side_failure(rows, report_run.baseline_simulation_run_id),
        reform=_side_failure(rows, report_run.reform_simulation_run_id),
    )
