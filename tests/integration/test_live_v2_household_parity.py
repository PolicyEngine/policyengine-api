"""Live staging parity of v2 household calculations with API v1's ``/calculate``.

Each household is stored through ``/v2/households``, calculated through
``/v2/household-calculations`` (the v2 household function on Modal) and, as
the same situation, through API v1's in-process ``/calculate`` on the same
candidate. Every calculated value must match, axes included. A run-specific
input makes each household new, so no earlier calculation is reused.
"""

from __future__ import annotations

import pytest

from tests.fixtures.integration.live_household_calculations import (
    YEAR,
    LiveHousehold,
    calculate,
    calculate_with_v1,
    household_differences,
    store_household,
)

CALCULATED = {YEAR: None}


def _probe_amount(integration_probe_id: str) -> int:
    """Return a small run-specific amount that makes each household new."""
    return int(integration_probe_id.rsplit("-", 1)[-1], 16) % 997


def _parity_households(probe_amount: int) -> list[LiveHousehold]:
    return [
        LiveHousehold(
            name="us-single-california",
            country_id="us",
            people={
                "adult": {
                    "age": {YEAR: 35},
                    "employment_income": {YEAR: 42_000 + probe_amount},
                    "income_tax": CALCULATED,
                }
            },
            groups={
                "household": {
                    "state_name": {YEAR: "CA"},
                    "household_net_income": CALCULATED,
                },
                "tax_unit": {"eitc": CALCULATED, "ctc": CALCULATED},
                "spm_unit": {"snap": CALCULATED},
            },
        ),
        LiveHousehold(
            name="us-couple-two-children-texas-axes",
            country_id="us",
            people={
                "first-adult": {"age": {YEAR: 38}},
                "second-adult": {
                    "age": {YEAR: 36},
                    "employment_income": {YEAR: 15_000 + probe_amount},
                },
                "first-child": {"age": {YEAR: 7}},
                "second-child": {"age": {YEAR: 3}},
            },
            groups={
                "household": {
                    "state_name": {YEAR: "TX"},
                    "household_net_income": CALCULATED,
                },
                "tax_unit": {"eitc": CALCULATED, "ctc": CALCULATED},
                "spm_unit": {"snap": CALCULATED},
            },
            axes=[
                [
                    {
                        "name": "employment_income",
                        "count": 5,
                        "min": 0,
                        "max": 100_000,
                        "period": YEAR,
                    }
                ]
            ],
        ),
        LiveHousehold(
            name="uk-single",
            country_id="uk",
            people={
                "adult": {
                    "age": {YEAR: 30},
                    "employment_income": {YEAR: 28_000 + probe_amount},
                    "income_tax": CALCULATED,
                    "national_insurance": CALCULATED,
                }
            },
            groups={"household": {"household_net_income": CALCULATED}},
        ),
        LiveHousehold(
            name="uk-couple-child-axes",
            country_id="uk",
            people={
                "first-adult": {"age": {YEAR: 34}},
                "second-adult": {
                    "age": {YEAR: 33},
                    "employment_income": {YEAR: 9_000 + probe_amount},
                },
                "child": {"age": {YEAR: 4}},
            },
            groups={
                "household": {"household_net_income": CALCULATED},
                "benunit": {
                    "universal_credit": CALCULATED,
                    "child_benefit": CALCULATED,
                },
            },
            axes=[
                [
                    {
                        "name": "employment_income",
                        "count": 5,
                        "min": 0,
                        "max": 60_000,
                        "period": YEAR,
                    }
                ]
            ],
        ),
    ]


PARITY_NAMES = [household.name for household in _parity_households(0)]


@pytest.mark.parametrize("household_name", PARITY_NAMES)
def test_a_v2_household_calculation_matches_api_v1(
    api_client, integration_probe_id, household_name
):
    (household,) = [
        candidate
        for candidate in _parity_households(_probe_amount(integration_probe_id))
        if candidate.name == household_name
    ]
    household_id = store_household(api_client, household)

    finished = calculate(api_client, household, household_id)
    v1_answer = calculate_with_v1(api_client, household)

    assert finished.item["status"] == "succeeded", finished.item["error"]
    result = finished.item["result"]
    differences = household_differences(v1_answer["result"], result["household"])
    assert differences == [], "\n".join(differences[:50])
    assert result["warnings"] == v1_answer.get("warnings", [])
    if household.country_id == "us":
        assert result["spm_config"] is not None
        assert result["spm_provenance"] is not None
