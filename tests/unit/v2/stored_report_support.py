"""Builders, stand-in services and messages for the v2 report and simulation tests.

The route tests and the simulation service client's tests share the messages
for an answer that may follow a record the service created.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi.testclient import TestClient
from flask import Flask

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.simulation_service.types import PackageVersions
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResult,
)
from policyengine_api.services.v2.stored_reports.types import (
    ReportRead,
    ReportRunRead,
    ReportSimulationRead,
    ReportSummaryRead,
)
from policyengine_api.services.v2.stored_simulations.types import (
    SimulationRead,
    SimulationRunRead,
)
from tests.fixtures.economy_results import us_economy_result

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from policyengine_api.fastapi_routes.resource_service_protocols import (
        V2StoredReportResourceService,
        V2StoredSimulationResourceService,
    )
    from policyengine_api.services.v2.simulation_service.types import (
        EconomyReportCreationInput,
        EconomySimulationCreationInput,
    )

REPORT_ID = UUID("00000000-0000-0000-0000-00000000a001")
REPORT_RUN_ID = UUID("00000000-0000-0000-0000-00000000a002")
BASELINE_SIMULATION_ID = UUID("00000000-0000-0000-0000-00000000a003")
REFORM_SIMULATION_ID = UUID("00000000-0000-0000-0000-00000000a004")
BASELINE_RUN_ID = UUID("00000000-0000-0000-0000-00000000a005")
REFORM_RUN_ID = UUID("00000000-0000-0000-0000-00000000a006")
POLICY_ID = UUID("00000000-0000-0000-0000-00000000a007")
SIMULATION_RUN_ID = UUID("00000000-0000-0000-0000-00000000a008")
CREATED_AT = datetime(2026, 11, 1, 9, tzinfo=UTC)
CURRENT_VERSIONS = PackageVersions(
    country_package_version="1.5.0", policyengine_version="4.2.0"
)


def submit_again(record: str) -> str:
    """Return the sentence asking the caller to submit the ``record`` again."""
    return (
        f"Submit the {record} again; if the first request went through, this "
        f"creates a second {record}."
    )


def answer_lost_message(error: str, record: str) -> str:
    """Return the message for an answer lost after the request may have arrived.

    ``error`` is the transport error's type or what a proxy answered.
    """
    return (
        "The simulation service may have received the request, but its answer "
        f"was lost ({error}). {submit_again(record)}"
    )


def possibly_created_message(status_and_code: str, record: str) -> str:
    """Return the message for a failure that may follow a created ``record``.

    ``status_and_code`` is the service's status and, when it gave one, its
    code, such as ``503 modal_call_refused``.
    """
    return (
        f"The simulation service may have created the {record}, but it failed "
        f"({status_and_code}). {submit_again(record)}"
    )


def report_run_read(**changes: Any) -> ReportRunRead:
    values: dict[str, Any] = {
        "id": REPORT_RUN_ID,
        "status": "succeeded",
        "trigger": "initial",
        "country_package_version": "1.4.0",
        "policyengine_version": "4.1.0",
        "baseline_simulation_run_id": BASELINE_RUN_ID,
        "reform_simulation_run_id": REFORM_RUN_ID,
        "error_message": None,
        "created_at": CREATED_AT,
        "started_at": CREATED_AT,
        "completed_at": CREATED_AT,
    }
    return ReportRunRead(**{**values, **changes})


def report_summary_fields(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "id": REPORT_ID,
        "country_id": "us",
        "kind": "economy",
        "label": "Expanded child tax credit",
        "description": None,
        "year": 2026,
        "region_code": "state/ca",
        "dataset_name": None,
        "baseline_simulation": ReportSimulationRead(
            id=BASELINE_SIMULATION_ID, policy_id=None, dynamic_id=None
        ),
        "reform_simulation": ReportSimulationRead(
            id=REFORM_SIMULATION_ID, policy_id=POLICY_ID, dynamic_id=None
        ),
        "options": {"include_cliffs": False},
        "created_at": CREATED_AT,
        "status": "succeeded",
        "run": report_run_read(),
        "current_versions": CURRENT_VERSIONS,
    }
    return {**values, **changes}


def report_summary_read(**changes: Any) -> ReportSummaryRead:
    return ReportSummaryRead(**report_summary_fields(**changes))


def report_read(**changes: Any) -> ReportRead:
    fields = {
        "result": EconomyResult.model_validate(us_economy_result()),
        **report_summary_fields(),
        **changes,
    }
    return ReportRead(**fields)


def simulation_read(**changes: Any) -> SimulationRead:
    values: dict[str, Any] = {
        "id": BASELINE_SIMULATION_ID,
        "country_id": "us",
        "kind": "economy",
        "policy_id": POLICY_ID,
        "dynamic_id": None,
        "household_id": None,
        "year": 2026,
        "region_code": "us",
        "dataset_name": "enhanced_cps_2024",
        "created_at": CREATED_AT,
        "status": "pending",
        "run": SimulationRunRead(
            id=SIMULATION_RUN_ID,
            year=2026,
            status="pending",
            country_package_version="1.5.0",
            policyengine_version="4.2.0",
            error_message=None,
            created_at=CREATED_AT,
            started_at=None,
            completed_at=None,
        ),
        "current_versions": CURRENT_VERSIONS,
    }
    return SimulationRead(**{**values, **changes})


@dataclass
class FakeReportService:
    """Answer with ``report`` or raise ``error``, recording each call."""

    report: ReportRead = field(default_factory=report_read)
    listed: tuple[ReportSummaryRead, ...] = ()
    error: Exception | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def _answer(self, name: str, **arguments: Any) -> None:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error

    def get_report(self, *, country_id: str, report_id: UUID) -> ReportRead:
        self._answer("get_report", country_id=country_id, report_id=report_id)
        return self.report

    def list_reports(
        self, *, country_id: str, report_ids: Sequence[UUID]
    ) -> tuple[ReportSummaryRead, ...]:
        self._answer("list_reports", country_id=country_id, report_ids=report_ids)
        return self.listed

    def create_report(self, report_input: EconomyReportCreationInput) -> ReportRead:
        self._answer("create_report", report_input=report_input)
        return self.report


@dataclass
class FakeSimulationService:
    """Answer with ``simulation`` or raise ``error``, recording each call."""

    simulation: SimulationRead = field(default_factory=simulation_read)
    error: Exception | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def _answer(self, name: str, **arguments: Any) -> None:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error

    def get_simulation(self, *, country_id: str, simulation_id: UUID) -> SimulationRead:
        self._answer(
            "get_simulation", country_id=country_id, simulation_id=simulation_id
        )
        return self.simulation

    def create_simulation(
        self, simulation_input: EconomySimulationCreationInput
    ) -> SimulationRead:
        self._answer("create_simulation", simulation_input=simulation_input)
        return self.simulation


def report_route_client(
    *,
    reports: V2StoredReportResourceService | None = None,
    simulations: V2StoredSimulationResourceService | None = None,
) -> TestClient:
    """Serve the report and simulation routes over these services, usually stand-ins."""
    factories: dict[str, Callable[[], Any]] = {}
    if reports is not None:
        factories["v2_stored_report_service_factory"] = lambda: reports
    if simulations is not None:
        factories["v2_stored_simulation_service_factory"] = lambda: simulations
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        **factories,
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        )
    )
