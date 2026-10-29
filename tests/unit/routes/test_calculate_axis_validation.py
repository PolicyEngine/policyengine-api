"""Household axes that policyengine-core cannot expand get a 400, not a 500.

The country is policyengine-core's example model behind the API's own country
adapter, so each household reaches policyengine-core's
``SimulationBuilder.expand_axes`` exactly as a production request does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from flask import Flask

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.v1_models import Household, Policy
from policyengine_api.extensions import cache
from policyengine_api.routes import household_routes
from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.household_calculations import (
    HouseholdCalculationCache,
)
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
)
from tests.fixtures.template_country import (
    TEMPLATE_PERIOD,
    TemplateCountry,
    template_household,
)

if TYPE_CHECKING:
    from flask.testing import FlaskClient

CALCULATION_ROUTES = ("/us/calculate", "/us/calculate-full")
# What policyengine-core raises while it expands axes it cannot use.
CORE_EXPANSION_ERRORS = (
    AttributeError,
    IndexError,
    KeyError,
    TypeError,
    ValueError,
    ZeroDivisionError,
)


def salary_axis(**fields: object) -> dict:
    """Return an axis over the first person's salary, with ``fields`` replaced."""
    return {
        "name": "salary",
        "period": TEMPLATE_PERIOD,
        "min": 0,
        "max": 3_000,
        "count": 3,
        **fields,
    }


def rent_axis(**fields: object) -> dict:
    """Return an axis over the household's rent, with ``fields`` replaced."""
    return {
        "name": "rent",
        "period": TEMPLATE_PERIOD,
        "min": 0,
        "max": 1_000,
        "count": 2,
        **fields,
    }


def without(axis: dict, field: str) -> dict:
    """Return a copy of ``axis`` without ``field``."""
    return {key: value for key, value in axis.items() if key != field}


def household_with_axes(axes: object) -> dict:
    """Return the example household with ``axes`` set."""
    return {**template_household(), "axes": axes}


# Each case: the axes, the location of the axis (or axes value) at fault, and the
# axis field at fault, or None when the fault is the value's structure.
REJECTED_AXES = [
    pytest.param(
        [[without(salary_axis(), "max")]],
        "household.axes[0][0]",
        "max",
        id="missing max",
    ),
    pytest.param(
        [[salary_axis()], [rent_axis(max=None)]],
        "household.axes[1][0]",
        "max",
        id="null max in a grid",
    ),
    pytest.param(
        [[salary_axis(max=None)]],
        "household.axes[0][0]",
        "max",
        id="null max",
    ),
    pytest.param(
        [[salary_axis(max="3000")]],
        "household.axes[0][0]",
        "max",
        id="string max",
    ),
    pytest.param(
        [[salary_axis(max=[1, 2])]],
        "household.axes[0][0]",
        "max",
        id="list max",
    ),
    pytest.param(
        [[salary_axis(max=float("nan"))]],
        "household.axes[0][0]",
        "max",
        id="NaN max",
    ),
    pytest.param(
        [[salary_axis(max=float("inf"))]],
        "household.axes[0][0]",
        "max",
        id="infinite max",
    ),
    pytest.param(
        [[without(salary_axis(), "min")]],
        "household.axes[0][0]",
        "min",
        id="missing min",
    ),
    pytest.param(
        [[without(salary_axis(), "count")]],
        "household.axes[0][0]",
        "count",
        id="missing count",
    ),
    pytest.param(
        [[salary_axis(count=None)]],
        "household.axes[0][0]",
        "count",
        id="null count",
    ),
    pytest.param(
        [[salary_axis(count=3.0)]],
        "household.axes[0][0]",
        "count",
        id="decimal count",
    ),
    pytest.param(
        [[salary_axis(count="3")]],
        "household.axes[0][0]",
        "count",
        id="string count",
    ),
    pytest.param(
        [[salary_axis(count=0)]],
        "household.axes[0][0]",
        "count",
        id="zero count",
    ),
    pytest.param(
        [[salary_axis(count=-1)]],
        "household.axes[0][0]",
        "count",
        id="negative count",
    ),
    pytest.param(
        [[without(salary_axis(), "name")]],
        "household.axes[0][0]",
        "name",
        id="missing name",
    ),
    pytest.param(
        [[salary_axis(name=["salary"])]],
        "household.axes[0][0]",
        "name",
        id="list name",
    ),
    pytest.param(
        [[salary_axis(period=None)]],
        "household.axes[0][0]",
        "period",
        id="null period in a single axis group",
    ),
    pytest.param(
        [[salary_axis(period="January")]],
        "household.axes[0][0]",
        "period",
        id="unparseable period",
    ),
    pytest.param(
        [[salary_axis(index=1.0)]],
        "household.axes[0][0]",
        "index",
        id="decimal index",
    ),
    pytest.param(
        [[salary_axis(index="1")]],
        "household.axes[0][0]",
        "index",
        id="string index",
    ),
    pytest.param(
        [[salary_axis(), without(salary_axis(index=1), "max")]],
        "household.axes[0][1]",
        "max",
        id="parallel axis without max",
    ),
    pytest.param(
        [[salary_axis(), 5]],
        "household.axes[0][1]",
        None,
        id="parallel axis that is not an object",
    ),
    pytest.param(
        [salary_axis()],
        "household.axes[0]",
        None,
        id="axis outside an axis group",
    ),
    pytest.param(
        [[]],
        "household.axes[0]",
        None,
        id="empty axis group",
    ),
    pytest.param(
        [[salary_axis()], {"0": rent_axis()}],
        "household.axes[1]",
        None,
        id="axis group that is an object",
    ),
    pytest.param(
        [[[salary_axis()]]],
        "household.axes[0][0]",
        None,
        id="axis nested in a list",
    ),
    pytest.param(
        {"salary": salary_axis()},
        "household.axes",
        None,
        id="axes object",
    ),
    pytest.param("salary", "household.axes", None, id="axes string"),
    pytest.param(True, "household.axes", None, id="axes true"),
]

ACCEPTED_AXES = [
    pytest.param(None, id="null axes"),
    pytest.param([], id="empty axes"),
    pytest.param([[salary_axis()]], id="one axis"),
    pytest.param([[salary_axis(count=1)]], id="one point"),
    pytest.param(
        [[salary_axis(), salary_axis(index=1, min=500, max=2_500)]],
        id="parallel axes",
    ),
    # policyengine-core reads the count of an axis group's first axis only.
    pytest.param(
        [[salary_axis(), without(salary_axis(index=1), "count")]],
        id="parallel axis without count",
    ),
    pytest.param([[salary_axis()], [rent_axis()]], id="grid"),
    # In a grid, an axis group of one point takes each axis's min only.
    pytest.param(
        [[salary_axis()], [without(rent_axis(count=1), "max")]],
        id="grid axis group of one point without max",
    ),
    # In a grid, a null period means the default period.
    pytest.param(
        [[salary_axis()], [rent_axis(period=None)]],
        id="null period in a grid",
    ),
    pytest.param([[without(salary_axis(), "period")]], id="default period"),
    pytest.param([[salary_axis(index=None)]], id="null index"),
    pytest.param([[salary_axis(index=1)]], id="second person's index"),
    # policyengine-core reads JSON booleans as the numbers 0 and 1.
    pytest.param(
        [[salary_axis(min=False, max=True, count=True)]],
        id="boolean numbers",
    ),
]


@pytest.fixture(scope="module")
def template_country() -> TemplateCountry:
    return TemplateCountry()


def make_flask_client():
    app = Flask(__name__)
    app.config.update(TESTING=True, CACHE_TYPE="NullCache")
    cache.init_app(app)
    app.register_blueprint(household_routes.household_bp)
    return app.test_client()


@dataclass(frozen=True)
class CalculationClient:
    """A Flask test client and a record of the observability IDs its requests start."""

    client: FlaskClient
    observability_id_starts: Mock


@pytest.fixture
def calculation_client(monkeypatch, template_country) -> CalculationClient:
    monkeypatch.setattr(
        household_routes,
        "household_calculation_service",
        HouseholdCalculationService(country_provider=lambda: {"us": template_country}),
    )
    observability_id_starts = Mock()
    monkeypatch.setattr(
        household_routes, "start_observability_id", observability_id_starts
    )
    return CalculationClient(make_flask_client(), observability_id_starts)


def assert_rejected_axis(response, axis_path: str, field: str | None) -> None:
    """Check the response is the invalid-input 400 for one axis problem."""
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["result"] is None
    assert [
        (error["type"], error["name"], error["path"]) for error in payload["errors"]
    ] == [
        (
            "household_axis",
            field or "axes",
            axis_path if field is None else f"{axis_path}.{field}",
        )
    ]
    error_message = payload["errors"][0]["message"]
    assert payload["message"] == f"Invalid calculate input(s): {error_message}"
    assert f"`{axis_path}`" in error_message
    if field is not None:
        assert f"`{field}`" in error_message


@pytest.mark.parametrize("route", CALCULATION_ROUTES)
@pytest.mark.parametrize(("axes", "axis_path", "field"), REJECTED_AXES)
def test_calculation_routes_reject_axes_that_cannot_be_expanded(
    calculation_client, route, axes, axis_path, field
):
    response = calculation_client.client.post(
        route, json={"household": household_with_axes(axes)}
    )

    assert_rejected_axis(response, axis_path, field)
    calculation_client.observability_id_starts.assert_not_called()


@pytest.mark.parametrize(("axes", "axis_path", "field"), REJECTED_AXES)
def test_policyengine_core_cannot_expand_the_rejected_axes(
    template_country, axes, axis_path, field
):
    with pytest.raises(CORE_EXPANSION_ERRORS):
        template_country.prepare_calculation(household_with_axes(axes), None)


@pytest.mark.parametrize("route", CALCULATION_ROUTES)
@pytest.mark.parametrize("axes", ACCEPTED_AXES)
def test_calculation_routes_accept_axes_that_policyengine_core_expands(
    calculation_client, route, axes
):
    response = calculation_client.client.post(
        route, json={"household": household_with_axes(axes)}
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_calculate_full_names_the_axis_without_a_max(calculation_client):
    response = calculation_client.client.post(
        "/us/calculate-full",
        json={"household": household_with_axes([[without(salary_axis(), "max")]])},
    )

    assert response.status_code == 400
    message = (
        "Household axis `household.axes[0][0]` (`salary`) needs `max` to be a "
        "finite number, but it is missing."
    )
    assert response.get_json() == {
        "status": "error",
        "message": f"Invalid calculate input(s): {message}",
        "result": None,
        "errors": [
            {
                "type": "household_axis",
                "name": "max",
                "path": "household.axes[0][0].max",
                "message": message,
            }
        ],
    }


def test_stored_household_calculation_rejects_axes_that_cannot_be_expanded(
    monkeypatch, orm_session_factory, template_country
):
    with orm_session_factory.begin() as session:
        session.add_all(
            [
                Household(
                    id=1,
                    country_id="us",
                    label=None,
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    household_json=household_with_axes(
                        [[without(salary_axis(), "max")]]
                    ),
                    household_hash="household-hash",
                ),
                Policy(
                    id=2,
                    country_id="us",
                    label=None,
                    api_version=COUNTRY_PACKAGE_VERSIONS["us"],
                    policy_json={},
                    policy_hash="policy-hash",
                ),
            ]
        )
    monkeypatch.setattr(
        household_routes,
        "household_calculation_service",
        HouseholdCalculationService(
            primary_session_factory=orm_session_factory,
            cache=HouseholdCalculationCache(
                InMemoryCacheBackend(), CacheNamespace("test", "api")
            ),
            country_provider=lambda: {"us": template_country},
        ),
    )
    monkeypatch.setattr(
        household_routes, "get_v1_household_read_source", lambda: "cloud_sql"
    )

    response = make_flask_client().get("/us/household/1/policy/2")

    assert_rejected_axis(response, "household.axes[0][0]", "max")
