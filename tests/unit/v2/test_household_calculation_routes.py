"""The /v2/household-calculations routes: submit a stored household, then poll it."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from flask import Flask

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.household_calculations.services import (
    V2HouseholdCalculationService,
)
from policyengine_api.services.v2.household_calculations.types import (
    SimulationServiceInvalidRequestError,
    SimulationServiceRefusedError,
    SimulationServiceUnavailableError,
)
from tests.unit.v2.household_calculation_support import (
    CALCULATION_ID,
    HOUSEHOLD_ID,
    POLICY_ID,
    SPM_CONFIG,
    SPM_PROVENANCE,
    FakeCatalogs,
    FakeCountries,
    FakeHouseholds,
    FakePolicies,
    FakeSimulation,
    succeeded_calculation,
)

PATH = "/v2/household-calculations"


class App:
    """A client of the native app serving household calculations over fakes."""

    def __init__(self, countries: FakeCountries | None = None) -> None:
        """Build the fakes and the app."""
        self.simulation = FakeSimulation()
        self.households = FakeHouseholds()
        self.service = V2HouseholdCalculationService(
            countries=countries or FakeCountries(),
            households=self.households,
            policies=FakePolicies(),
            catalog_reader_factory=FakeCatalogs,
            simulation_factory=lambda: self.simulation,
        )
        dependencies = NativeRouteDependencies(
            readiness_probe=lambda: True,
            gateway_client_factory=lambda: None,
            metadata_reader_factory=lambda: None,
            specification_provider=dict,
            v2_household_calculation_service_factory=lambda: self.service,
        )
        settings = RouteImplementationSettings(
            health=RouteImplementation.FLASK_FALLBACK,
            specification=RouteImplementation.FLASK_FALLBACK,
            metadata=RouteImplementation.FLASK_FALLBACK,
        )
        self.client = TestClient(
            create_asgi_app(
                Flask(__name__), dependencies=dependencies, route_settings=settings
            ),
            raise_server_exceptions=False,
        )


def body(**changes: object) -> dict[str, object]:
    """Return a request calculating the stored household under the reform."""
    request: dict[str, object] = {
        "country_id": "us",
        "household_id": str(HOUSEHOLD_ID),
        "policy_id": str(POLICY_ID),
    }
    request.update(changes)
    return request


def test_a_calculation_is_accepted_without_an_account() -> None:
    app = App()

    response = app.client.post(PATH, json=body())

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["result"]["calculation_id"] == str(CALCULATION_ID)
    assert payload["result"]["status"] == "running"
    assert payload["result"]["household_id"] == str(HOUSEHOLD_ID)
    assert payload["result"]["result"] is None


def test_a_calculation_with_axes_sends_them() -> None:
    app = App()
    axes = [[{"name": "employment_income", "count": 3, "min": 0, "max": 50000}]]

    response = app.client.post(PATH, json=body(axes=axes))

    assert response.status_code == 202
    assert app.simulation.submissions[0]["options"]["axes"] == axes


def test_a_succeeded_us_calculation_reads_back_its_spm_choice() -> None:
    app = App()
    app.simulation.read_answers[CALCULATION_ID] = succeeded_calculation()

    response = app.client.get(f"{PATH}/{CALCULATION_ID}")

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["status"] == "succeeded"
    assert result["result"]["spm_config"] == SPM_CONFIG
    assert result["result"]["spm_provenance"] == SPM_PROVENANCE
    assert result["result"]["warnings"] == [
        "The input `age_group` is deprecated and was ignored."
    ]


def test_a_country_without_household_calculations_gets_422_naming_it() -> None:
    app = App(
        FakeCountries(
            rows=(
                CountryRead(
                    id="us", household_enabled=False, society_wide_enabled=False
                ),
            )
        )
    )

    response = app.client.post(PATH, json=body())

    assert response.status_code == 422
    assert "us" in response.json()["message"]
    assert app.simulation.submissions == []


def test_a_household_only_country_is_accepted() -> None:
    app = App()
    stored = app.households.households[("us", HOUSEHOLD_ID)]
    app.households.households[("uk", HOUSEHOLD_ID)] = stored.__class__(
        **{
            **stored.__dict__,
            "country_id": "uk",
            "household_data": {
                "people": [
                    {
                        "id": "person-1",
                        "values": {},
                        "memberships": {
                            "household": "household-1",
                            "benunit": "benunit-1",
                        },
                    }
                ],
                "household": [{"id": "household-1", "values": {}}],
                "benunit": [{"id": "benunit-1", "values": {}}],
            },
        }
    )

    response = app.client.post(PATH, json=body(country_id="uk", policy_id=None))

    assert response.status_code == 202


@pytest.mark.parametrize(
    "changes",
    [{"household_id": str(uuid4())}, {"policy_id": str(uuid4())}],
    ids=["household", "policy"],
)
def test_an_unknown_household_or_policy_is_not_found(changes) -> None:
    response = App().client.post(PATH, json=body(**changes))

    assert response.status_code == 404


def test_an_unknown_calculation_is_not_found() -> None:
    assert App().client.get(f"{PATH}/{uuid4()}").status_code == 404


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (SimulationServiceUnavailableError("unreachable"), 503),
        (SimulationServiceRefusedError("no household function"), 503),
    ],
    ids=["unreachable", "refused"],
)
def test_a_simulation_service_that_cannot_calculate_answers_503(
    error, status_code
) -> None:
    app = App()
    app.simulation.error = error

    response = app.client.post(PATH, json=body())

    assert response.status_code == status_code


@pytest.mark.parametrize(
    "changes",
    [
        {"axes": [[{"name": "employment_income", "count": 0, "min": 0, "max": 1}]]},
        {
            "axes": [
                [
                    {"name": "employment_income", "count": 3, "min": 0, "max": 1},
                    {"name": "age", "count": 4, "min": 20, "max": 60},
                ]
            ]
        },
        {
            "axes": [
                [{"name": "employment_income", "count": 101, "min": 0, "max": 1}],
                [{"name": "age", "count": 100, "min": 20, "max": 60}],
            ]
        },
        {"country_id": "ca"},
        {"unexpected": True},
        {"year": 2026},
        {"force": True},
    ],
    ids=[
        "axis-count",
        "parallel-axes-of-different-counts",
        "too-many-axis-points",
        "country",
        "unknown-field",
        "year",
        "force",
    ],
)
def test_a_malformed_request_is_refused_before_anything_is_read(changes) -> None:
    app = App()

    response = app.client.post(PATH, json=body(**changes))

    assert response.status_code == 422
    assert app.simulation.submissions == []


def test_a_household_the_simulation_service_finds_invalid_gets_422_with_why() -> None:
    app = App()
    app.simulation.error = SimulationServiceInvalidRequestError(
        "The simulation service cannot calculate this household: "
        "household.households.household-1.members: List should have at least 1 item"
    )

    response = app.client.post(PATH, json=body())

    assert response.status_code == 422
    assert "members" in response.json()["message"]


def test_axis_groups_within_the_point_limit_are_accepted() -> None:
    app = App()
    axes = [
        [
            {"name": "employment_income", "count": 100, "min": 0, "max": 1},
            {"name": "self_employment_income", "count": 100, "min": 0, "max": 1},
        ],
        [{"name": "age", "count": 100, "min": 20, "max": 60}],
    ]

    response = app.client.post(PATH, json=body(axes=axes))

    assert response.status_code == 202
