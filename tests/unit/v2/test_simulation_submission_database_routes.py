"""Create v2 reports and simulations through the routes and database-backed checks.

The countries and policies services read a SQLite database with the v2
tables, so the policy check runs the real catalog query; only the simulation
service is a stand-in, which a refused submission never reaches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import (
    V2_METADATA,
    Country,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.countries.database_session import (
    CountryDatabaseSession,
)
from policyengine_api.services.v2.countries.services import V2CountryService
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import V2PolicyService
from policyengine_api.services.v2.simulation_service.services import (
    SimulationSubmissionService,
)
from policyengine_api.services.v2.simulation_service.types import (
    EconomyReportCreationInput,
    EconomySimulationCreationInput,
    SubmittedReport,
    SubmittedSimulation,
)
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from policyengine_api.services.v2.stored_simulations.database_session import (
    StoredSimulationDatabaseSession,
)
from policyengine_api.services.v2.stored_simulations.services import (
    V2StoredSimulationService,
)
from tests.unit.v2.stored_report_support import CURRENT_VERSIONS, report_route_client

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient
    from sqlalchemy import Engine

RUNNING_VERSION = "6.10.0"
EARLIER_VERSION = "6.9.0"
KEPT_PARAMETER = "gov.example.rate"
REMOVED_PARAMETER = "gov.example.removed_rate"
STORED_AT = datetime(2026, 11, 10, tzinfo=UTC)
REPORTS = "/v2/reports?country_id=us"
SIMULATIONS = "/v2/simulations?country_id=us"


@dataclass
class RecordingSimulationService:
    """The simulation service's client, recording what it is sent."""

    reports: list[EconomyReportCreationInput] = field(default_factory=list)
    simulations: list[EconomySimulationCreationInput] = field(default_factory=list)

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        self.reports.append(report)
        return SubmittedReport(report_id=uuid4(), report_run_id=uuid4())

    def submit_simulation(
        self, simulation: EconomySimulationCreationInput
    ) -> SubmittedSimulation:
        self.simulations.append(simulation)
        return SubmittedSimulation(simulation_id=uuid4(), simulation_run_id=uuid4())


@pytest.fixture
def engine() -> Iterator[Engine]:
    # One connection shared by every thread, so the route's worker thread
    # reads the same in-memory database.
    database_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(database_engine)
    yield database_engine
    database_engine.dispose()


def store_catalog_version(
    session: Session, model: TaxBenefitModel, version: str, names: list[str]
) -> dict[str, Parameter]:
    """Store a catalog version of ``model`` with these parameters, keyed by name."""
    model_version = TaxBenefitModelVersion(
        model=model, version=version, current_law_id=1, metadata_time_periods=[2026]
    )
    parameters = {
        name: Parameter(name=name, tax_benefit_model_version=model_version)
        for name in names
    }
    session.add(model_version)
    session.add_all(parameters.values())
    session.flush()
    return parameters


def store_policy(
    session: Session, parameters: dict[str, Parameter], content_hash_letter: str
) -> Policy:
    """Store a US policy setting each of ``parameters``, of their catalog version."""
    model_version = next(iter(parameters.values())).tax_benefit_model_version
    policy = Policy(
        country_id="us",
        tax_benefit_model_id=model_version.model_id,
        tax_benefit_model_version_id=model_version.id,
        canonicalization_version=1,
        content_hash=content_hash_letter * 64,
        created_at=STORED_AT,
        updated_at=STORED_AT,
    )
    session.add(policy)
    session.flush()
    session.add_all(
        ParameterValue(
            parameter_id=parameter.id,
            value_json=0.2,
            start_date=STORED_AT,
            policy_id=policy.id,
        )
        for parameter in parameters.values()
    )
    return policy


@pytest.fixture
def stored_policy_ids(engine: Engine) -> dict[str, UUID]:
    """Store the US with two catalog versions and three policies.

    ``outdated_policy`` sets a parameter the running catalog version removed;
    ``kept_policy`` was made on the earlier version too, but sets only a
    parameter the running version still has; ``running_policy`` was made on
    the running version.
    """
    with Session(engine, expire_on_commit=False) as session:
        session.add(Country(id="us", household_enabled=True, society_wide_enabled=True))
        model = TaxBenefitModel(name="policyengine-us")
        earlier = store_catalog_version(
            session, model, EARLIER_VERSION, [KEPT_PARAMETER, REMOVED_PARAMETER]
        )
        running = store_catalog_version(
            session, model, RUNNING_VERSION, [KEPT_PARAMETER]
        )
        policies = {
            "outdated_policy": store_policy(session, earlier, "a"),
            "kept_policy": store_policy(
                session, {KEPT_PARAMETER: earlier[KEPT_PARAMETER]}, "b"
            ),
            "running_policy": store_policy(session, running, "c"),
        }
        session.commit()
    return {name: policy.id for name, policy in policies.items()}


@pytest.fixture
def simulation_service() -> RecordingSimulationService:
    return RecordingSimulationService()


@pytest.fixture
def submissions(
    engine: Engine, simulation_service: RecordingSimulationService
) -> SimulationSubmissionService:
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    return SimulationSubmissionService(
        countries=V2CountryService(CountryDatabaseSession(sessions)),
        policies=V2PolicyService(
            PolicyDatabaseSession(sessions),
            running_policyengine_version=RUNNING_VERSION,
        ),
        client_factory=lambda: simulation_service,
    )


@pytest.fixture
def client(engine: Engine, submissions: SimulationSubmissionService) -> TestClient:
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    return report_route_client(
        reports=V2StoredReportService(
            StoredReportDatabaseSession(sessions),
            current_versions=lambda _country_id: CURRENT_VERSIONS,
            submissions=submissions,
        ),
        simulations=V2StoredSimulationService(
            StoredSimulationDatabaseSession(sessions),
            current_versions=lambda _country_id: CURRENT_VERSIONS,
            submissions=submissions,
        ),
    )


def report_body(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "economy",
        "label": "Expanded child tax credit",
        "year": 2026,
        "region_code": "us",
        "baseline": {},
        "reform": {},
    }
    return {**values, **changes}


def simulation_body(policy_id: UUID) -> dict[str, Any]:
    return {
        "country_id": "us",
        "kind": "economy",
        "year": 2026,
        "region_code": "us",
        "policy_id": str(policy_id),
    }


@pytest.mark.parametrize("side", ["baseline", "reform"])
def test_a_report_whose_policy_sets_parameters_the_running_catalog_lacks_is_refused(
    client: TestClient,
    stored_policy_ids: dict[str, UUID],
    simulation_service: RecordingSimulationService,
    side: str,
) -> None:
    outdated_policy_id = stored_policy_ids["outdated_policy"]

    response = client.post(
        REPORTS,
        json=report_body(**{side: {"policy_id": str(outdated_policy_id)}}),
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "status": "error",
        "message": (
            f"Policy {outdated_policy_id} sets parameters the running catalog "
            f"version does not have: {REMOVED_PARAMETER}"
        ),
        "code": "missing_parameters",
        "missing_parameters": [REMOVED_PARAMETER],
    }
    assert simulation_service.reports == []


def test_a_simulation_whose_policy_sets_parameters_the_running_catalog_lacks_is_refused(
    client: TestClient,
    stored_policy_ids: dict[str, UUID],
    simulation_service: RecordingSimulationService,
) -> None:
    response = client.post(
        SIMULATIONS, json=simulation_body(stored_policy_ids["outdated_policy"])
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "missing_parameters"
    assert response.json()["missing_parameters"] == [REMOVED_PARAMETER]
    assert simulation_service.simulations == []


def test_policies_whose_parameters_all_exist_in_the_running_catalog_are_sent(
    submissions: SimulationSubmissionService,
    stored_policy_ids: dict[str, UUID],
    simulation_service: RecordingSimulationService,
) -> None:
    report = EconomyReportCreationInput.model_validate(
        report_body(
            baseline={"policy_id": str(stored_policy_ids["kept_policy"])},
            reform={"policy_id": str(stored_policy_ids["running_policy"])},
        )
    )
    simulation = EconomySimulationCreationInput.model_validate(
        simulation_body(stored_policy_ids["kept_policy"])
    )

    submissions.submit_report(report)
    submissions.submit_simulation(simulation)

    assert simulation_service.reports == [report]
    assert simulation_service.simulations == [simulation]


@pytest.mark.parametrize("record", ["report", "simulation"])
def test_a_catalog_that_cannot_be_queried_answers_503(
    engine: Engine,
    client: TestClient,
    stored_policy_ids: dict[str, UUID],
    simulation_service: RecordingSimulationService,
    record: str,
) -> None:
    running_policy_id = stored_policy_ids["running_policy"]
    # The policy check's catalog query reads this table; nothing else does.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE tax_benefit_model_versions"))

    if record == "report":
        response = client.post(
            REPORTS, json=report_body(reform={"policy_id": str(running_policy_id)})
        )
    else:
        response = client.post(SIMULATIONS, json=simulation_body(running_policy_id))

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "V2 storage is unavailable",
    }
    assert simulation_service.reports == []
    assert simulation_service.simulations == []
