"""Live staging parity of v2 household calculations with API v1's ``/calculate``.

Each household is stored through ``/v2/households`` (and its reform through
``/v2/policies``), calculated through ``/v2/household-calculations`` (the v2
household function on Modal) and, as the same situation and policy, through
API v1's in-process ``/calculate`` (``/calculate-full`` when it adds missing
variables) on the same candidate. Every calculated value must match, axes,
reforms and added variables included. A run-specific input makes each
household new, so no earlier calculation is reused.
"""

from __future__ import annotations

import pytest

from tests.fixtures.integration.live_household_calculations import (
    YEAR,
    LiveHousehold,
    calculate,
    calculate_with_v1,
    household_differences,
    probe_amount,
    store_household,
    store_reform,
)

CALCULATED = {YEAR: None}


def _parity_households(run_amount: int) -> list[LiveHousehold]:
    return [
        LiveHousehold(
            name="us-single-california",
            country_id="us",
            people={
                "adult": {
                    "age": {YEAR: 35},
                    "employment_income": {YEAR: 42_000 + run_amount},
                    # Deprecated: dropped with a warning by both calculations.
                    "medical_out_of_pocket_expenses": {YEAR: 1_000},
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
            expects_warnings=True,
        ),
        LiveHousehold(
            name="us-couple-two-children-texas-axes",
            country_id="us",
            people={
                "first-adult": {"age": {YEAR: 38}},
                "second-adult": {
                    "age": {YEAR: 36},
                    "employment_income": {YEAR: 15_000 + run_amount},
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
            name="us-single-reform-added-variables",
            country_id="us",
            people={
                "adult": {
                    "age": {YEAR: 29},
                    "employment_income": {YEAR: 61_000 + run_amount},
                }
            },
            groups={"household": {"state_name": {YEAR: "NY"}}},
            reform={"gov.irs.deductions.standard.amount.SINGLE": 20_000},
            add_missing_variables=True,
        ),
        LiveHousehold(
            name="uk-single",
            country_id="uk",
            people={
                "adult": {
                    "age": {YEAR: 30},
                    "employment_income": {YEAR: 28_000 + run_amount},
                    "income_tax": CALCULATED,
                    "national_insurance": CALCULATED,
                }
            },
            groups={"household": {"household_net_income": CALCULATED}},
        ),
        LiveHousehold(
            name="uk-single-reform",
            country_id="uk",
            people={
                "adult": {
                    "age": {YEAR: 41},
                    "employment_income": {YEAR: 36_000 + run_amount},
                    "income_tax": CALCULATED,
                }
            },
            groups={"household": {"household_net_income": CALCULATED}},
            reform={"gov.hmrc.income_tax.allowances.personal_allowance.amount": 15_000},
        ),
        LiveHousehold(
            name="uk-couple-child-axes",
            country_id="uk",
            people={
                "first-adult": {"age": {YEAR: 34}},
                "second-adult": {
                    "age": {YEAR: 33},
                    "employment_income": {YEAR: 9_000 + run_amount},
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
        for candidate in _parity_households(probe_amount(integration_probe_id))
        if candidate.name == household_name
    ]
    household_id = store_household(api_client, household)
    policy_id = store_reform(api_client, household)

    finished = calculate(api_client, household, household_id, policy_id)
    v1_answer = calculate_with_v1(api_client, household)

    assert finished.item["status"] == "succeeded", finished.item["error"]
    result = finished.item["result"]
    differences = household_differences(v1_answer["result"], result["household"])
    assert differences == [], "\n".join(differences[:50])
    # The v2 database orders each stored record's keys itself, so warnings,
    # listed in the household's key order, may come in another order.
    assert sorted(result["warnings"]) == sorted(v1_answer.get("warnings", []))
    assert bool(result["warnings"]) == household.expects_warnings
    if household.country_id == "us":
        assert result["spm_config"] is not None
        assert result["spm_provenance"] is not None
