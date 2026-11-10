"""Read household calculations from ``household_jobs`` as the Public API's runtime role.

The simulation service inserts the jobs and its Modal workers record their
results; the Public API only reads them, through the household calculation
service, as ``policyengine_v2_runtime``. Its declared privileges must cover
the read, so a statement they don't allow fails here as it would in staging
and production (rule ``api.v2.runtime-privileges-tested-as-runtime-role``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from policyengine_api.constants import REPO
from policyengine_api.services.v2.countries.database_session import (
    CountryDatabaseSession,
)
from policyengine_api.services.v2.countries.services import V2CountryService
from policyengine_api.services.v2.household_calculations.database_session import (
    HouseholdCalculationDatabaseSession,
)
from policyengine_api.services.v2.household_calculations.services import (
    V2HouseholdCalculationService,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationNotFoundError,
)
from policyengine_api.services.v2.households.database_session import (
    HouseholdDatabaseSession,
)
from policyengine_api.services.v2.households.services import V2HouseholdService
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import V2PolicyService
from tests.fixtures.household_calculation_documents import (
    CALCULATED_HOUSEHOLD,
    FAILURE_SUMMARY,
    INPUT_ERROR,
    SPM_CONFIG,
    SPM_PROVENANCE,
    WARNING,
    failed_document,
    succeeded_document,
)
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    PublicApiRows,
    delete_public_api_rows,
    insert_public_api_rows,
    insert_row,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

COMPLETED_AT = datetime(2026, 11, 10, 12, 0, 9, tzinfo=UTC)


@dataclass(frozen=True)
class StoredJobs:
    """The jobs stored for one test, by what happened to them."""

    public_api_rows: PublicApiRows
    succeeded: UUID
    refused: UUID
    failed_unexpectedly: UUID
    pending: UUID


def _insert_job(
    connection, rows: PublicApiRows, job_id: UUID, status: str, **columns: object
) -> None:
    insert_row(
        connection,
        "household_jobs",
        id=job_id,
        country="us",
        household_id=rows.household_id,
        year=2026,
        request_data="{}",
        tax_benefit_model_version_id=rows.version_id,
        status=status,
        **RUN_VERSIONS,
        **columns,
    )


@pytest.fixture
def stored_jobs(disposable_v2_database_url, managed_v2_roles) -> Iterator[StoredJobs]:
    """Commit, as the superuser, one job of each outcome; delete them afterwards.

    The service reads on connections of its own, so the rows are committed
    rather than left in a transaction the test rolls back.
    """
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    with engine.begin() as connection:
        rows = insert_public_api_rows(connection)
        jobs = StoredJobs(
            public_api_rows=rows,
            succeeded=uuid4(),
            refused=uuid4(),
            failed_unexpectedly=uuid4(),
            pending=uuid4(),
        )
        _insert_job(
            connection,
            rows,
            jobs.succeeded,
            "succeeded",
            # A json column keeps the document's text, so its key order too.
            result=json.dumps(succeeded_document()),
            completed_at=COMPLETED_AT,
        )
        _insert_job(
            connection,
            rows,
            jobs.refused,
            "failed",
            result=json.dumps(failed_document()),
            error_message=FAILURE_SUMMARY,
            completed_at=COMPLETED_AT,
        )
        _insert_job(
            connection,
            rows,
            jobs.failed_unexpectedly,
            "failed",
            error_message="household_function_error: the Modal call ended",
            completed_at=COMPLETED_AT,
        )
        _insert_job(connection, rows, jobs.pending, "pending")
    try:
        yield jobs
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM household_jobs WHERE household_id = :household_id"),
                {"household_id": rows.household_id},
            )
            delete_public_api_rows(connection, rows)
        engine.dispose()


def _no_simulation_service():
    msg = "reading a household calculation never calls the simulation service"
    raise AssertionError(msg)


@pytest.fixture
def runtime_service(managed_v2_roles, v2_engine_as_role):
    """Return the household calculation service, reading as the runtime role."""
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    sessions = sessionmaker(runtime_engine, class_=Session)
    yield V2HouseholdCalculationService(
        countries=V2CountryService(CountryDatabaseSession(sessions)),
        households=V2HouseholdService(HouseholdDatabaseSession(sessions)),
        policies=V2PolicyService(
            PolicyDatabaseSession(sessions), running_policyengine_version="6.10.0"
        ),
        database_session=HouseholdCalculationDatabaseSession(sessions),
        simulation_factory=_no_simulation_service,
    )
    runtime_engine.dispose()


def test_the_runtime_role_reads_a_succeeded_calculation_in_its_stored_order(
    stored_jobs, runtime_service
) -> None:
    calculation = runtime_service.get_calculation(stored_jobs.succeeded)

    assert calculation.calculation_id == stored_jobs.succeeded
    assert calculation.household_id == stored_jobs.public_api_rows.household_id
    assert calculation.catalog_version_id == stored_jobs.public_api_rows.version_id
    assert calculation.policy_id is None
    assert calculation.status == "succeeded"
    assert calculation.completed_at == COMPLETED_AT
    assert calculation.error is None
    assert calculation.result is not None
    assert json.dumps(calculation.result.household) == json.dumps(CALCULATED_HOUSEHOLD)
    assert calculation.result.warnings == (WARNING,)
    assert calculation.result.spm_config == SPM_CONFIG
    assert calculation.result.spm_provenance == SPM_PROVENANCE


def test_the_runtime_role_reads_why_a_calculation_failed(
    stored_jobs, runtime_service
) -> None:
    refused = runtime_service.get_calculation(stored_jobs.refused)
    failed_unexpectedly = runtime_service.get_calculation(
        stored_jobs.failed_unexpectedly
    )

    assert refused.status == "failed"
    assert refused.result is None
    assert refused.error is not None
    assert refused.error.code == "invalid_inputs"
    assert refused.error.input_errors == (INPUT_ERROR,)
    assert failed_unexpectedly.error is not None
    assert failed_unexpectedly.error.code is None
    assert (
        failed_unexpectedly.error.message
        == "household_function_error: the Modal call ended"
    )


def test_the_runtime_role_reads_an_unfinished_calculation(
    stored_jobs, runtime_service
) -> None:
    calculation = runtime_service.get_calculation(stored_jobs.pending)

    assert calculation.status == "pending"
    assert calculation.started_at is None
    assert calculation.completed_at is None
    assert calculation.result is None
    assert calculation.error is None


def test_an_unknown_calculation_is_not_found(stored_jobs, runtime_service) -> None:
    with pytest.raises(HouseholdCalculationNotFoundError):
        runtime_service.get_calculation(uuid4())
