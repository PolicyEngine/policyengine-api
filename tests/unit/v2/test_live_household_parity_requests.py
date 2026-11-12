"""The live parity checks' requests to the Public API's own calculation routes.

Each parity household goes to ``/calculate`` (``/calculate-full`` when it adds
missing variables) as the check sends it. The real routes check its inputs and
parse its situation with the installed country models, and only the
calculation itself is left out, so a household the routes refuse before
calculating fails here rather than in a release. A refusal during the
calculation, such as an SPM error, is not covered. The check waits longer than
the candidate's Cloud
Run request timeout (``CLOUD_RUN_TIMEOUT`` in
``.github/scripts/cloud_run_env.sh``) for the answer: ``/calculate-full`` can
take most of it, and the check should get the candidate's own answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from flask import Flask

from policyengine_api.country import COUNTRIES
from policyengine_api.extensions import cache
from policyengine_api.routes import household_routes
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationResult,
    HouseholdCalculationService,
    PreparedHouseholdCalculation,
)
from tests.fixtures.integration.live_household_calculations import (
    LiveHousehold,
    calculate_with_v1,
)
from tests.integration.test_live_v2_household_parity import parity_households
from tests.unit.cloud_run_deploy_support import run_bash, script_env

if TYPE_CHECKING:
    from collections.abc import Iterator

PARITY_HOUSEHOLDS = parity_households(0)


class UncalculatedHouseholds(HouseholdCalculationService):
    """The routes' household service, answering each accepted household uncalculated.

    Input checks and situation parsing run as in the Public API; the
    calculation, which takes minutes for ``/calculate-full``, does not. The
    answer is the household as the routes prepared it: deprecated inputs
    dropped and, for ``/calculate-full``, the missing variables added.
    """

    def calculate_prepared_household(
        self, prepared: PreparedHouseholdCalculation
    ) -> HouseholdCalculationResult:
        return HouseholdCalculationResult(
            household=prepared.household_json, warnings=prepared.warnings
        )


@pytest.fixture
def public_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[httpx.Client]:
    """Call the Public API's calculation routes with the installed country models."""
    monkeypatch.setattr(
        household_routes,
        "household_calculation_service",
        UncalculatedHouseholds(country_provider=lambda: COUNTRIES),
    )
    app = Flask(__name__)
    app.config.update(TESTING=True, CACHE_TYPE="NullCache")
    cache.init_app(app)
    app.register_blueprint(household_routes.household_bp)
    with httpx.Client(
        base_url="http://public-api.test", transport=httpx.WSGITransport(app=app)
    ) as client:
        yield client


def candidate_request_timeout_seconds() -> float:
    """Return how long Cloud Run lets a request to the candidate run."""
    result = run_bash(
        "-c",
        "source .github/scripts/cloud_run_env.sh && cloud_run_set_defaults"
        ' && printf "%s" "$CLOUD_RUN_TIMEOUT"',
        env=script_env(),
    )
    assert result.returncode == 0, result.stderr
    return float(result.stdout)


@pytest.mark.parametrize(
    "household",
    PARITY_HOUSEHOLDS,
    ids=[parity_household.name for parity_household in PARITY_HOUSEHOLDS],
)
def test_the_public_api_accepts_each_parity_household(
    public_api: httpx.Client, household: LiveHousehold
) -> None:
    answer = calculate_with_v1(public_api, household)

    assert answer["status"] == "ok"


@pytest.mark.parametrize(
    "household",
    [
        LiveHousehold(name="calculate", country_id="us", people={"you": {}}),
        LiveHousehold(
            name="calculate-full",
            country_id="us",
            people={"you": {}},
            add_missing_variables=True,
        ),
    ],
    ids=["calculate", "calculate-full"],
)
def test_the_check_waits_longer_than_the_candidate_lets_a_request_run(
    household: LiveHousehold,
) -> None:
    read_timeouts: list[float | None] = []

    def answer(request: httpx.Request) -> httpx.Response:
        read_timeouts.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json={"status": "ok", "result": {}})

    with httpx.Client(
        base_url="https://public-api.example", transport=httpx.MockTransport(answer)
    ) as client:
        calculate_with_v1(client, household)

    (read_timeout,) = read_timeouts
    assert read_timeout is not None
    assert read_timeout > candidate_request_timeout_seconds()
