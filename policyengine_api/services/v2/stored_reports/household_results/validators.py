"""Checks of the calculated households a household report run's simulations stored."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from policyengine_api.services.v2.household_calculations.types import (
    StoredExecutionResult,
)
from policyengine_api.services.v2.stored_reports.household_results.types import (
    HouseholdReportResult,
    HouseholdResultUnreadableError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import ReportRun
    from policyengine_api.services.v2.household_calculations.types import (
        HouseholdCalculationOutput,
    )
    from policyengine_api.services.v2.stored_reports.household_results.types import (
        HouseholdResultRows,
    )


def _calculated_household(
    rows: HouseholdResultRows, simulation_run_id: UUID
) -> HouseholdCalculationOutput:
    """Return one simulation run's calculated household.

    Raise HouseholdResultUnreadableError when the run does not exist or its
    document is not a version 1 result document with a calculated household.
    """
    if simulation_run_id not in rows.documents:
        msg = f"simulation run {simulation_run_id} does not exist"
        raise HouseholdResultUnreadableError(msg)
    try:
        document = StoredExecutionResult.model_validate(
            rows.documents[simulation_run_id]
        )
    except ValidationError as error:
        msg = f"simulation run {simulation_run_id} has no readable household result"
        raise HouseholdResultUnreadableError(msg) from error
    return document.calculation_output()


def require_household_report_result(
    report_run: ReportRun, rows: HouseholdResultRows
) -> HouseholdReportResult:
    """Return a succeeded report run's calculated households.

    The reform's is read only when the run names a reform simulation run.
    Raise HouseholdResultUnreadableError when either cannot be read.
    """
    reform_run_id = report_run.reform_simulation_run_id
    return HouseholdReportResult(
        baseline=_calculated_household(rows, report_run.baseline_simulation_run_id),
        reform=None
        if reform_run_id is None
        else _calculated_household(rows, reform_run_id),
    )
