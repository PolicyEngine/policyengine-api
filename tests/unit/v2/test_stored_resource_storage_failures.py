"""A failed database read in the report and simulation services is a typed error."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from policyengine_api.services.v2.stored_reports.validators import ReportStorageError
from policyengine_api.services.v2.stored_simulations.services import (
    V2StoredSimulationService,
)
from policyengine_api.services.v2.stored_simulations.validators import (
    SimulationStorageError,
)
from tests.unit.v2.stored_report_support import CURRENT_VERSIONS

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
