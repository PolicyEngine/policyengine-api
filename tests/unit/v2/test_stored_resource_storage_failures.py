"""A failed database read in the report and simulation services is a typed error."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from policyengine_api.services.v2.simulation_service.types import (
    EconomyReportCreationInput,
    EconomySimulationCreationInput,
    SubmittedReport,
    SubmittedSimulation,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from policyengine_api.services.v2.stored_reports.validators import (
    CreatedReportUnreadableError,
    ReportStorageError,
)
from policyengine_api.services.v2.stored_simulations.services import (
    V2StoredSimulationService,
)
from policyengine_api.services.v2.stored_simulations.validators import (
    CreatedSimulationUnreadableError,
    SimulationStorageError,
)
from tests.unit.v2.stored_report_support import (
    CURRENT_VERSIONS,
    REPORT_ID,
    REPORT_RUN_ID,
    SIMULATION_RUN_ID,
)

CREATED_SIMULATION_ID = uuid4()

if TYPE_CHECKING:
    from collections.abc import Iterator


CONNECTION_REFUSED = OperationalError(
    "SELECT 1", {}, ConnectionRefusedError("connection refused")
)


class UnreachableDatabase:
    """A database session whose reads fail as an unreachable database's do."""

    @contextmanager
    def read(self) -> Iterator[Any]:
        raise CONNECTION_REFUSED
        yield


def test_report_reads_raise_a_storage_error_when_the_database_fails() -> None:
    service = V2StoredReportService(
        UnreachableDatabase(),
        current_versions=lambda country_id: CURRENT_VERSIONS,
    )

    with pytest.raises(ReportStorageError):
        service.get_report(country_id="us", report_id=uuid4())
    with pytest.raises(ReportStorageError):
        service.list_reports(country_id="us", report_ids=[uuid4()])


def test_simulation_reads_raise_a_storage_error_when_the_database_fails() -> None:
    service = V2StoredSimulationService(
        UnreachableDatabase(),
        current_versions=lambda country_id: CURRENT_VERSIONS,
    )

    with pytest.raises(SimulationStorageError):
        service.get_simulation(country_id="us", simulation_id=uuid4())


class CreatingSimulationService:
    """The simulation service, answering that it created each submission."""

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        return SubmittedReport(report_id=REPORT_ID, report_run_id=REPORT_RUN_ID)

    def submit_simulation(
        self, simulation: EconomySimulationCreationInput
    ) -> SubmittedSimulation:
        return SubmittedSimulation(
            simulation_id=CREATED_SIMULATION_ID, simulation_run_id=SIMULATION_RUN_ID
        )


def test_a_created_report_the_database_cannot_read_back_is_named() -> None:
    # The simulation service created the report, so the caller must get its
    # ID rather than an answer that invites submitting it again.
    service = V2StoredReportService(
        UnreachableDatabase(),
        current_versions=lambda country_id: CURRENT_VERSIONS,
        submissions=CreatingSimulationService(),
    )

    with pytest.raises(CreatedReportUnreadableError) as unreadable:
        service.create_report(
            EconomyReportCreationInput(
                country_id="us",
                kind="economy",
                label="Expanded child tax credit",
                year=2026,
                region_code="us",
                baseline={},
                reform={},
            )
        )

    assert unreadable.value.report_id == REPORT_ID
    assert isinstance(unreadable.value.__cause__, ReportStorageError)


def test_a_created_simulation_the_database_cannot_read_back_is_named() -> None:
    service = V2StoredSimulationService(
        UnreachableDatabase(),
        current_versions=lambda country_id: CURRENT_VERSIONS,
        submissions=CreatingSimulationService(),
    )

    with pytest.raises(CreatedSimulationUnreadableError) as unreadable:
        service.create_simulation(
            EconomySimulationCreationInput(
                country_id="us", kind="economy", year=2026, region_code="us"
            )
        )

    assert unreadable.value.simulation_id == CREATED_SIMULATION_ID
    assert isinstance(unreadable.value.__cause__, SimulationStorageError)
