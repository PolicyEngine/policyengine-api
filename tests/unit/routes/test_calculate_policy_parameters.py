"""A household calculation's policy may set only parameters, not parameter groups.

The checks use the metadata of the loaded US and UK models. The metadata lists
groups, scales and scale brackets too, with the type ``parameterNode``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Flask

from policyengine_api.country import COUNTRIES
from policyengine_api.extensions import cache
from policyengine_api.routes import household_routes
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationService,
)
from tests.fixtures.policy_parameter_paths import (
    NON_PARAMETER_CASES,
    POLICY_PERIOD,
    SETTABLE_PARAMETER_PATHS,
)

HOUSEHOLD = {"people": {"you": {"age": {"2026": 40}}}}


class MetadataOnlyCountry:
    """A loaded model's metadata, with a calculation that must never be reached."""

    def __init__(self, country_id: str) -> None:
        self.metadata = COUNTRIES[country_id].metadata

    def calculate(self, *_args, **_kwargs):
        pytest.fail("a refused calculation request must not be calculated")


def _calculation_service(country_id: str) -> HouseholdCalculationService:
    country = MetadataOnlyCountry(country_id)
    return HouseholdCalculationService(country_provider=lambda: {country_id: country})


def _calculate_client(monkeypatch, country_id: str):
    monkeypatch.setattr(
        household_routes,
        "household_calculation_service",
        _calculation_service(country_id),
    )
    app = Flask(__name__)
    app.config.update(TESTING=True, CACHE_TYPE="NullCache")
    cache.init_app(app)
    app.register_blueprint(household_routes.household_bp)
    return app.test_client()


@pytest.mark.parametrize(("country_id", "non_parameter_path"), NON_PARAMETER_CASES)
def test_calculate_refuses_a_policy_path_that_is_not_a_parameter(
    monkeypatch,
    country_id,
    non_parameter_path,
):
    client = _calculate_client(monkeypatch, country_id)

    with patch.object(
        household_routes,
        "start_observability_id",
    ) as start_observability_id:
        response = client.post(
            f"/{country_id}/calculate",
            json={
                "household": HOUSEHOLD,
                "policy": {non_parameter_path: {POLICY_PERIOD: 1}},
            },
        )

    assert response.status_code == 400
    body = response.get_json()
    assert body["status"] == "error"
    assert body["result"] is None
    assert body["message"] == (
        "Unrecognized calculate input(s): Unrecognized policy parameter "
        f"`{non_parameter_path}` at `policy.{non_parameter_path}`."
    )
    assert body["errors"] == [
        {
            "type": "policy_parameter",
            "name": non_parameter_path,
            "path": f"policy.{non_parameter_path}",
            "message": (
                f"Unrecognized policy parameter `{non_parameter_path}` at "
                f"`policy.{non_parameter_path}`."
            ),
        }
    ]
    start_observability_id.assert_not_called()


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_calculation_accepts_bracket_and_contributed_parameters(country_id):
    policy = {
        parameter_path: {POLICY_PERIOD: 1}
        for parameter_path in SETTABLE_PARAMETER_PATHS[country_id]
    }

    prepared = _calculation_service(country_id).prepare_household_calculation(
        country_id,
        HOUSEHOLD,
        policy,
    )

    assert prepared.policy_json == policy
