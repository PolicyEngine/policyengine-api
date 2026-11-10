"""Conversions of household jobs and simulation answers into calculation results."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import HouseholdJobStatus
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationFailure,
    HouseholdCalculationOutput,
    HouseholdCalculationRead,
    HouseholdCalculationSubmitted,
    StoredExecutionFailure,
    StoredExecutionResult,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import HouseholdJob
    from policyengine_api.services.v2.household_calculations.types import (
        HouseholdCalculationAccepted,
        HouseholdCalculationInput,
        HouseholdJobStatusName,
    )

# The error of a failed job that records neither a failure document nor an
# error message.
UNEXPLAINED_FAILURE = "The household calculation failed."
STATUS_NAMES: dict[HouseholdJobStatus, HouseholdJobStatusName] = {
    HouseholdJobStatus.PENDING: "pending",
    HouseholdJobStatus.RUNNING: "running",
    HouseholdJobStatus.SUCCEEDED: "succeeded",
    HouseholdJobStatus.FAILED: "failed",
}


def _calculation_output(document: StoredExecutionResult) -> HouseholdCalculationOutput:
    (policy_result,) = document.output.results
    return HouseholdCalculationOutput(
        household=policy_result.household,
        warnings=tuple(policy_result.warnings),
        spm_config=document.output.spm_config,
        spm_provenance=policy_result.spm_provenance,
    )


def _calculation_failure(
    document: StoredExecutionFailure | None, error_message: str | None
) -> HouseholdCalculationFailure:
    if document is None:
        return HouseholdCalculationFailure(
            code=None,
            message=error_message or UNEXPLAINED_FAILURE,
            input_errors=(),
            spm_error=None,
        )
    error = document.error
    return HouseholdCalculationFailure(
        code=error.code,
        message=error.message,
        input_errors=tuple(error.input_errors),
        spm_error=error.spm_error,
    )


def household_calculation_read(
    job: HouseholdJob,
    outcome: StoredExecutionResult | StoredExecutionFailure | None,
) -> HouseholdCalculationRead:
    """Return the calculation a household job records.

    ``outcome`` is the job's result document, already read as its status says
    (``stored_household_outcome``). A succeeded job's result is its one policy
    result; a failed job's error is its failure document's error, or else its
    error message.
    """
    status = STATUS_NAMES[HouseholdJobStatus(job.status)]
    return HouseholdCalculationRead(
        calculation_id=job.id,
        country_id=job.country,
        household_id=job.household_id,
        policy_id=job.policy_id,
        year=job.year,
        catalog_version_id=job.tax_benefit_model_version_id,
        country_package_version=job.country_package_version,
        policyengine_version=job.policyengine_version,
        status=status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=(
            _calculation_output(outcome)
            if status == "succeeded" and isinstance(outcome, StoredExecutionResult)
            else None
        ),
        error=(
            _calculation_failure(
                outcome if isinstance(outcome, StoredExecutionFailure) else None,
                job.error_message,
            )
            if status == "failed"
            else None
        ),
    )


def household_calculation_submitted(
    calculation: HouseholdCalculationInput,
    accepted: HouseholdCalculationAccepted,
    *,
    year: int,
) -> HouseholdCalculationSubmitted:
    """Return the accepted calculation with what it calculates."""
    return HouseholdCalculationSubmitted(
        calculation_id=accepted.calculation_id,
        status=accepted.status,
        country_id=calculation.country_id,
        household_id=calculation.household_id,
        policy_id=calculation.policy_id,
        year=year,
    )
