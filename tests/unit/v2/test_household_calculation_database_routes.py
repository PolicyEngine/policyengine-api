"""Submit household calculations through the route and the database-backed services.

The countries, households and policies services read a SQLite database with
the v2 tables, so the policy check runs the real catalog query; only the
simulation service is a stand-in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from flask import Flask
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.models import (
    V2_METADATA,
    Country,
    Household,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.libs.simulation_household_calculations import (
    SimulationHouseholdCalculationClient,
)
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.observability.identifiers import OBSERVABILITY_ID_HEADER
from policyengine_api.request_context import REQUEST_ID_HEADER
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
from policyengine_api.services.v2.households.database_session import (
    HouseholdDatabaseSession,
)
from policyengine_api.services.v2.households.services import V2HouseholdService
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import V2PolicyService
from tests.fixtures.household_calculation_documents import JOB_ID
from tests.unit.v2.household_calculation_support import FakeSimulation

RUNNING_VERSION = "6.10.0"
EARLIER_VERSION = "6.9.0"
KEPT_PARAMETER = "gov.example.rate"
REMOVED_PARAMETER = "gov.example.removed_rate"
CALCULATIONS = "/v2/household-calculations"
STORED_AT = datetime(2026, 11, 10, tzinfo=UTC)


@pytest.fixture
def engine():
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


def _catalog_version(
    session: Session, model: TaxBenefitModel, version: str, names: list[str]
) -> dict[str, Parameter]:
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


def _policy(session: Session, parameters: dict[str, Parameter], hash_seed: str):
    model_version = next(iter(parameters.values())).tax_benefit_model_version
    policy = Policy(
        country_id="us",
        tax_benefit_model_id=model_version.model_id,
        tax_benefit_model_version_id=model_version.id,
        canonicalization_version=1,
        content_hash=hash_seed * 64,
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
def stored(engine) -> dict[str, object]:
    """Store the US, a household, and a policy on each of two catalog versions."""
    with Session(engine, expire_on_commit=False) as session:
        session.add(Country(id="us", household_enabled=True, society_wide_enabled=True))
        model = TaxBenefitModel(name="policyengine-us")
        earlier = _catalog_version(
            session, model, EARLIER_VERSION, [KEPT_PARAMETER, REMOVED_PARAMETER]
        )
        running = _catalog_version(session, model, RUNNING_VERSION, [KEPT_PARAMETER])
        household = Household(
            country_id="us",
            default_year=2026,
            household_data={"people": []},
            canonicalization_version=1,
            content_hash="c" * 64,
        )
        session.add(household)
        rows = {
            "household": household,
            "earlier_policy": _policy(session, earlier, "a"),
            "running_policy": _policy(session, running, "b"),
        }
        session.commit()
    return {name: row.id for name, row in rows.items()}


@pytest.fixture
def simulation() -> FakeSimulation:
    return FakeSimulation()


@pytest.fixture
def client(engine, simulation) -> TestClient:
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)

    def service() -> V2HouseholdCalculationService:
        return V2HouseholdCalculationService(
            countries=V2CountryService(CountryDatabaseSession(sessions)),
            households=V2HouseholdService(HouseholdDatabaseSession(sessions)),
            policies=V2PolicyService(
                PolicyDatabaseSession(sessions),
                running_policyengine_version=RUNNING_VERSION,
            ),
            database_session=HouseholdCalculationDatabaseSession(sessions),
            simulation_factory=lambda: simulation,
        )

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_household_calculation_service_factory=service,
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        ),
        raise_server_exceptions=False,
    )


def _body(stored, policy: str | None) -> dict[str, object]:
    return {
        "country_id": "us",
        "household_id": str(stored["household"]),
        "policy_id": None if policy is None else str(stored[policy]),
    }


def test_a_stored_household_is_submitted_after_the_database_backed_checks(
    client, stored, simulation
) -> None:
    response = client.post(CALCULATIONS, json=_body(stored, "running_policy"))

    assert response.status_code == 202
    assert response.json()["result"]["item"]["calculation_id"] == str(JOB_ID)
    (sent,) = simulation.submissions
    assert sent.policy_id == stored["running_policy"]


def test_a_policy_setting_parameters_the_running_catalog_lacks_is_refused(
    client, stored, simulation
) -> None:
    response = client.post(CALCULATIONS, json=_body(stored, "earlier_policy"))

    assert response.status_code == 422
    assert response.json()["code"] == "missing_parameters"
    assert response.json()["missing_parameters"] == [REMOVED_PARAMETER]
    assert simulation.submissions == []


def test_an_unknown_household_is_not_found_in_the_database(
    client, stored, simulation
) -> None:
    body = {**_body(stored, None), "household_id": str(uuid4())}

    response = client.post(CALCULATIONS, json=body)

    assert response.status_code == 404
    assert simulation.submissions == []


def test_a_catalog_that_cannot_be_queried_answers_503(
    engine, client, stored, simulation
) -> None:
    # The policy check's catalog query reads this table; nothing else does.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE tax_benefit_model_versions"))

    response = client.post(CALCULATIONS, json=_body(stored, "running_policy"))

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "V2 household calculation storage is unavailable",
    }
    assert simulation.submissions == []


GATEWAY_AND_ENTRYPOINT_VARIABLES = (
    "GATEWAY_AUTH_ISSUER",
    "GATEWAY_AUTH_AUDIENCE",
    "GATEWAY_AUTH_CLIENT_ID",
    "GATEWAY_AUTH_CLIENT_SECRET",
    "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE",
    "GATEWAY_AUTH_REQUIRED",
    "SIM_ENTRYPOINT",
)


class SimulationRecorder:
    """The simulation service, answering every submission 202 and recording it."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(202, json={"job_id": str(JOB_ID), "status": "pending"})


@pytest.fixture
def simulation_recorder(monkeypatch) -> SimulationRecorder:
    """Configure the Cloud Run simulation service, with no gateway credentials."""
    for name in GATEWAY_AND_ENTRYPOINT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", "https://simulation.example.test")
    return SimulationRecorder()


@pytest.fixture
def client_with_simulation_client(engine, simulation_recorder) -> TestClient:
    """Serve the route with the real simulation client over a recording transport."""
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    transport = httpx.MockTransport(simulation_recorder.answer)

    def service() -> V2HouseholdCalculationService:
        return V2HouseholdCalculationService(
            countries=V2CountryService(CountryDatabaseSession(sessions)),
            households=V2HouseholdService(HouseholdDatabaseSession(sessions)),
            policies=V2PolicyService(
                PolicyDatabaseSession(sessions),
                running_policyengine_version=RUNNING_VERSION,
            ),
            database_session=HouseholdCalculationDatabaseSession(sessions),
            simulation_factory=lambda: (
                SimulationHouseholdCalculationClient.from_environment(
                    transport=transport
                )
            ),
        )

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_household_calculation_service_factory=service,
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        ),
        raise_server_exceptions=False,
    )


def test_the_submission_carries_the_request_and_callers_observability_ids(
    client_with_simulation_client, stored, simulation_recorder
) -> None:
    observability_id = str(uuid4())

    response = client_with_simulation_client.post(
        CALCULATIONS,
        json=_body(stored, "running_policy"),
        headers={OBSERVABILITY_ID_HEADER: observability_id},
    )

    assert response.status_code == 202
    (sent,) = simulation_recorder.requests
    assert str(sent.url) == "https://simulation.example.test/household-calculations"
    assert sent.headers[REQUEST_ID_HEADER] == response.headers[REQUEST_ID_HEADER]
    assert sent.headers[OBSERVABILITY_ID_HEADER] == observability_id
    # The 202 returns the ID the simulation service received.
    assert response.headers[OBSERVABILITY_ID_HEADER] == observability_id


def test_a_submission_without_an_observability_id_is_given_one(
    client_with_simulation_client, stored, simulation_recorder
) -> None:
    response = client_with_simulation_client.post(
        CALCULATIONS, json=_body(stored, None)
    )

    assert response.status_code == 202
    (sent,) = simulation_recorder.requests
    assert UUID(sent.headers[OBSERVABILITY_ID_HEADER])
    assert (
        response.headers[OBSERVABILITY_ID_HEADER]
        == (sent.headers[OBSERVABILITY_ID_HEADER])
    )


def test_a_refused_submission_returns_no_observability_id(
    client_with_simulation_client, stored, simulation_recorder
) -> None:
    body = {**_body(stored, None), "household_id": str(uuid4())}

    response = client_with_simulation_client.post(CALCULATIONS, json=body)

    assert response.status_code == 404
    assert simulation_recorder.requests == []
    assert OBSERVABILITY_ID_HEADER not in response.headers
