"""Live staging checks of ``/v2/household-calculations``.

These run against the tagged staging candidate, through staging API v1, the
staging Simulation Entrypoint, the v2 household functions on Modal and the
staging v2 database:

- a submit, poll and result cycle for a new US household;
- a latency check: several calculations submitted at once, so the Simulation
  Entrypoint serves them in parallel, each accepted within
  ``STAGING_HOUSEHOLD_SUBMIT_LIMIT_SECONDS`` and finished within
  ``STAGING_HOUSEHOLD_FINISH_LIMIT_SECONDS``;
- a memory check: a household varied across 401 points of employment income,
  with its net income calculated at each point, which must finish without
  failing; a household function that runs out of memory fails it.

The measured times are reported as a warning, so the job log keeps them.
"""

from __future__ import annotations

import os
import statistics
import warnings
from concurrent.futures import ThreadPoolExecutor

import httpx

from tests.fixtures.integration.live_household_calculations import (
    YEAR,
    FinishedCalculation,
    LiveHousehold,
    calculate,
    probe_amount,
    store_household,
)

PARALLEL_CALCULATIONS = int(os.environ.get("STAGING_HOUSEHOLD_PARALLEL_COUNT", "6"))
SUBMIT_LIMIT_SECONDS = float(
    os.environ.get("STAGING_HOUSEHOLD_SUBMIT_LIMIT_SECONDS", "10")
)
FINISH_LIMIT_SECONDS = float(
    os.environ.get("STAGING_HOUSEHOLD_FINISH_LIMIT_SECONDS", "300")
)
MEMORY_CHECK_POINTS = 401


class HouseholdCalculationMeasurement(UserWarning):
    """Times measured by the live household calculation checks."""


def _us_household(name: str, employment_income: int) -> LiveHousehold:
    return LiveHousehold(
        name=name,
        country_id="us",
        people={
            "adult": {
                "age": {YEAR: 40},
                "employment_income": {YEAR: employment_income},
            }
        },
        groups={
            "household": {
                "state_name": {YEAR: "NY"},
                "household_net_income": {YEAR: None},
            }
        },
    )


def test_a_us_household_is_submitted_polled_and_read(api_client, integration_probe_id):
    household = _us_household("cycle", 51_000 + probe_amount(integration_probe_id))
    household_id = store_household(api_client, household)

    finished = calculate(api_client, household, household_id)

    item = finished.item
    assert item["status"] == "succeeded", item["error"]
    assert item["household_id"] == household_id
    assert item["completed_at"] is not None
    result = item["result"]
    net_income = result["household"]["households"]["household-1"][
        "household_net_income"
    ][YEAR]
    assert isinstance(net_income, int | float)
    assert result["spm_config"] is not None
    assert result["spm_provenance"] is not None
    assert result["policyengine_version"]
    read_again = api_client.get(
        f"/v2/household-calculations/{item['calculation_id']}"
    ).json()["result"]
    assert read_again == item


def test_parallel_calculations_finish_within_the_latency_limits(
    api_base_url, integration_probe_id
):
    run_amount = probe_amount(integration_probe_id)
    households = [
        _us_household(f"parallel-{index}", 20_000 + 1_000 * index + run_amount)
        for index in range(PARALLEL_CALCULATIONS)
    ]

    def run(household: LiveHousehold) -> FinishedCalculation:
        with httpx.Client(base_url=api_base_url, timeout=90.0) as client:
            return calculate(client, household, store_household(client, household))

    with ThreadPoolExecutor(max_workers=PARALLEL_CALCULATIONS) as pool:
        outcomes = list(pool.map(run, households))

    submit_times = [outcome.submit_seconds for outcome in outcomes]
    finish_times = [outcome.total_seconds for outcome in outcomes]
    warnings.warn(
        HouseholdCalculationMeasurement(
            f"{PARALLEL_CALCULATIONS} parallel household calculations: submit "
            f"median {statistics.median(submit_times):.2f} s, longest "
            f"{max(submit_times):.2f} s; finish median "
            f"{statistics.median(finish_times):.1f} s, longest "
            f"{max(finish_times):.1f} s"
        ),
        stacklevel=1,
    )
    assert [outcome.item["status"] for outcome in outcomes] == ["succeeded"] * len(
        outcomes
    ), [outcome.item["error"] for outcome in outcomes]
    assert max(submit_times) <= SUBMIT_LIMIT_SECONDS, submit_times
    assert max(finish_times) <= FINISH_LIMIT_SECONDS, finish_times


def test_a_household_across_many_points_finishes(api_client, integration_probe_id):
    household = LiveHousehold(
        name="memory",
        country_id="us",
        people={"adult": {"age": {YEAR: 45}}},
        groups={
            "household": {
                "state_name": {YEAR: "CA"},
                "household_net_income": {YEAR: None},
            }
        },
        axes=[
            [
                {
                    "name": "employment_income",
                    "count": MEMORY_CHECK_POINTS,
                    "min": 0,
                    "max": 400_000 + probe_amount(integration_probe_id),
                    "period": YEAR,
                }
            ]
        ],
    )
    household_id = store_household(api_client, household)

    finished = calculate(api_client, household, household_id)

    warnings.warn(
        HouseholdCalculationMeasurement(
            f"Household across {MEMORY_CHECK_POINTS} points: submit "
            f"{finished.submit_seconds:.2f} s, finish {finished.total_seconds:.1f} s"
        ),
        stacklevel=1,
    )
    assert finished.item["status"] == "succeeded", finished.item["error"]
    net_income = finished.item["result"]["household"]["households"]["household-1"][
        "household_net_income"
    ][YEAR]
    assert len(net_income) == MEMORY_CHECK_POINTS
