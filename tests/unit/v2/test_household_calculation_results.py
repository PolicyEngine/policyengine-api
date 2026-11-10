"""Read a household job's status, result document and error into a calculation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from policyengine_api.services.v2.household_calculations.transformations import (
    household_calculation_read,
)

from policyengine_api.data.v2.models import HouseholdJob, HouseholdJobStatus
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationResultUnreadableError,
    stored_household_outcome,
)
from tests.fixtures.household_calculation_documents import (
    CALCULATED_HOUSEHOLD,
    FAILURE_SUMMARY,
    INPUT_ERROR,
    JOB_ID,
    SPM_CONFIG,
    SPM_PROVENANCE,
    WARNING,
    failed_document,
    succeeded_document,
)

HOUSEHOLD_ID = UUID("00000000-0000-4000-8000-0000000000a1")
POLICY_ID = UUID("00000000-0000-4000-8000-0000000000b1")
CATALOG_VERSION_ID = UUID("00000000-0000-4000-8000-0000000000e1")
CREATED_AT = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
STARTED_AT = datetime(2026, 11, 10, 12, 0, 5, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 11, 10, 12, 0, 9, tzinfo=UTC)


def _job(
    status: HouseholdJobStatus, *, result: object = None, **changes: object
) -> HouseholdJob:
    finished = status in {HouseholdJobStatus.SUCCEEDED, HouseholdJobStatus.FAILED}
    fields: dict[str, object] = {
        "id": JOB_ID,
        "created_at": CREATED_AT,
        "updated_at": COMPLETED_AT,
        "country": "us",
        "household_id": HOUSEHOLD_ID,
        "year": 2026,
        "request_data": {},
        "policy_id": POLICY_ID,
        "tax_benefit_model_version_id": CATALOG_VERSION_ID,
        "country_package_version": "1.450.0",
        "policyengine_version": "6.10.0",
        "status": status,
        "result": result,
        "started_at": None if status is HouseholdJobStatus.PENDING else STARTED_AT,
        "completed_at": COMPLETED_AT if finished else None,
    }
    fields.update(changes)
    return HouseholdJob(**fields)


def _read(job: HouseholdJob):
    return household_calculation_read(
        job, stored_household_outcome(job.id, job.status, job.result)
    )


def test_a_succeeded_job_reads_back_its_household_warnings_and_spm() -> None:
    calculation = _read(_job(HouseholdJobStatus.SUCCEEDED, result=succeeded_document()))

    assert calculation.calculation_id == JOB_ID
    assert calculation.country_id == "us"
    assert calculation.household_id == HOUSEHOLD_ID
    assert calculation.policy_id == POLICY_ID
    assert calculation.year == 2026
    assert calculation.catalog_version_id == CATALOG_VERSION_ID
    assert calculation.country_package_version == "1.450.0"
    assert calculation.policyengine_version == "6.10.0"
    assert calculation.status == "succeeded"
    assert (calculation.created_at, calculation.started_at) == (CREATED_AT, STARTED_AT)
    assert calculation.completed_at == COMPLETED_AT
    assert calculation.error is None
    assert calculation.result is not None
    assert calculation.result.household == CALCULATED_HOUSEHOLD
    assert calculation.result.warnings == (WARNING,)
    assert calculation.result.spm_config == SPM_CONFIG
    assert calculation.result.spm_provenance == SPM_PROVENANCE


def test_a_calculated_household_keeps_the_key_order_it_was_stored_in() -> None:
    calculation = _read(_job(HouseholdJobStatus.SUCCEEDED, result=succeeded_document()))

    assert calculation.result is not None
    household = calculation.result.household
    assert list(household) == list(CALCULATED_HOUSEHOLD)
    assert list(household["people"]["person-1"]) == ["employment_income", "age"]


def test_a_country_without_spm_reads_back_no_spm_choice_or_receipt() -> None:
    document = succeeded_document(
        country="uk",
        spm_config=None,
        results=[{"policy_key": "baseline", "household": CALCULATED_HOUSEHOLD}],
    )

    calculation = _read(_job(HouseholdJobStatus.SUCCEEDED, result=document))

    assert calculation.result is not None
    assert calculation.result.warnings == ()
    assert calculation.result.spm_config is None
    assert calculation.result.spm_provenance is None


def test_a_job_the_household_function_refused_reads_back_its_error() -> None:
    calculation = _read(
        _job(
            HouseholdJobStatus.FAILED,
            result=failed_document(),
            error_message=FAILURE_SUMMARY,
        )
    )

    assert calculation.status == "failed"
    assert calculation.result is None
    assert calculation.error is not None
    assert calculation.error.code == "invalid_inputs"
    assert calculation.error.message == (
        "The household names a variable the model lacks."
    )
    assert calculation.error.input_errors == (INPUT_ERROR,)
    assert calculation.error.spm_error is None


def test_a_job_that_failed_unexpectedly_reads_back_its_error_message() -> None:
    calculation = _read(
        _job(HouseholdJobStatus.FAILED, error_message="The Modal call ended.")
    )

    assert calculation.result is None
    assert calculation.error is not None
    assert calculation.error.code is None
    assert calculation.error.message == "The Modal call ended."
    assert calculation.error.input_errors == ()
    assert calculation.error.spm_error is None


@pytest.mark.parametrize(
    "document", [None, {"status": "failed"}, {"unexpected": True}, ["not", "a", "map"]]
)
def test_a_failed_job_without_a_readable_failure_says_it_failed(document) -> None:
    calculation = _read(_job(HouseholdJobStatus.FAILED, result=document))

    assert calculation.error is not None
    assert calculation.error.code is None
    assert calculation.error.message == "The household calculation failed."


@pytest.mark.parametrize(
    "status", [HouseholdJobStatus.PENDING, HouseholdJobStatus.RUNNING]
)
def test_an_unfinished_job_reads_back_no_result_or_error(status) -> None:
    calculation = _read(
        _job(status, result=succeeded_document(), error_message="not yet")
    )

    assert calculation.status == status.value
    assert calculation.completed_at is None
    assert calculation.result is None
    assert calculation.error is None


def test_a_document_with_fields_the_public_api_does_not_read_is_still_read() -> None:
    document = succeeded_document(added_by_a_later_contract={"any": "value"})
    document["added_at_the_top"] = True

    calculation = _read(_job(HouseholdJobStatus.SUCCEEDED, result=document))

    assert calculation.result is not None
    assert calculation.result.household == CALCULATED_HOUSEHOLD


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(None, id="no-document"),
        pytest.param(failed_document(), id="a-failure-document"),
        pytest.param(succeeded_document(results=[]), id="no-result"),
        pytest.param(
            succeeded_document(
                results=[
                    {"policy_key": "baseline", "household": CALCULATED_HOUSEHOLD},
                    {"policy_key": "reform", "household": CALCULATED_HOUSEHOLD},
                ]
            ),
            id="two-results",
        ),
        pytest.param(
            succeeded_document(
                results=[{"policy_key": "reform", "household": "not a household"}]
            ),
            id="malformed-household",
        ),
    ],
)
def test_a_succeeded_job_without_one_readable_result_is_unreadable(document) -> None:
    with pytest.raises(HouseholdCalculationResultUnreadableError, match=str(JOB_ID)):
        _read(_job(HouseholdJobStatus.SUCCEEDED, result=document))
