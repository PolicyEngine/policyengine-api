"""The live parity checks' requests to the Public API's own calculation routes.

Each parity household goes to ``/calculate`` (``/calculate-full`` when it adds
missing variables) as the check sends it, and must pass those routes' input
checks with the installed country models, so a household the routes refuse
fails here rather than in a release. The check waits longer than the
candidate's Cloud Run request timeout (``CLOUD_RUN_TIMEOUT`` in
``.github/scripts/cloud_run_env.sh``) for the answer: ``/calculate-full`` can
take most of it, and the check should get the candidate's own answer.
"""

from __future__ import annotations

import json

import httpx
import pytest

from policyengine_api.country import COUNTRIES
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationOptions,
    HouseholdCalculationService,
    InvalidHouseholdInputsError,
)
from policyengine_api.utils.input_validation import format_invalid_inputs_message
from tests.fixtures.integration.live_household_calculations import (
    LiveHousehold,
    calculate_with_v1,
)
from tests.integration.test_live_v2_household_parity import parity_households
from tests.unit.cloud_run_deploy_support import run_bash, script_env

PARITY_HOUSEHOLDS = parity_households(0)


class PublicApiInputChecks:
    """The Public API's calculation routes, answering once their input checks pass.

    A refused request gets the routes' 400; an accepted one gets its household
    back uncalculated. The read timeout of every request is recorded.
    """

    def __init__(self) -> None:
        self.service = HouseholdCalculationService(country_provider=lambda: COUNTRIES)
        self.read_timeouts: list[float | None] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.read_timeouts.append(request.extensions["timeout"]["read"])
        country_id, route = request.url.path.strip("/").split("/")
        payload = json.loads(request.content)
        try:
            self.service.prepare_household_calculation(
                country_id,
                payload["household"],
                payload.get("policy", {}),
                options=HouseholdCalculationOptions(
                    add_missing=route == "calculate-full"
                ),
            )
        except InvalidHouseholdInputsError as error:
            message = format_invalid_inputs_message(error.invalid_inputs)
            return httpx.Response(400, json={"status": "error", "message": message})
        return httpx.Response(
            200, json={"status": "ok", "result": payload["household"]}
        )

    def calculate(self, household: LiveHousehold) -> dict:
        with httpx.Client(
            base_url="https://public-api.example",
            transport=httpx.MockTransport(self.answer),
        ) as client:
            return calculate_with_v1(client, household)


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
def test_the_public_api_accepts_each_parity_household(household) -> None:
    answer = PublicApiInputChecks().calculate(household)

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
    household,
) -> None:
    public_api = PublicApiInputChecks()

    public_api.calculate(household)

    (read_timeout,) = public_api.read_timeouts
    assert read_timeout is not None
    assert read_timeout > candidate_request_timeout_seconds()
