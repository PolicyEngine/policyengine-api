"""Rebuild a budget window's result from the budget rows of its years' report runs.

Each year's report run stores an economy result, through the port of the
simulation service's writer in ``tests.fixtures.economy_results``; the
window's result is today's budget-window format, which the old simulation
gateway's ``budget_window_results.build_budget_window_result`` builds from
each year's budget figures.
"""

from __future__ import annotations

import copy
from typing import Any
from uuid import uuid4

import pytest

from policyengine_api.data.v2.models import BudgetSummary
from policyengine_api.services.v2.stored_reports.budget_window_results import (
    transformations as window_transformations,
)
from policyengine_api.services.v2.stored_reports.budget_window_results.types import (
    BudgetWindowResultRows,
    BudgetWindowResultUnreadableError,
    BudgetWindowYearRows,
)
from tests.fixtures.economy_results import (
    RunIds,
    economy_result_rows,
    uk_economy_result,
    us_economy_result,
)


def year_output(
    country: str, *, tax: float, state_tax: float, benefits: float
) -> dict[str, Any]:
    """Return an economy result of the country with these budget changes."""
    output = copy.deepcopy(
        us_economy_result() if country == "us" else uk_economy_result()
    )
    output["budget"].update(
        tax_revenue_impact=tax,
        state_tax_revenue_impact=state_tax,
        benefit_spending_impact=benefits,
        budgetary_impact=tax - benefits,
    )
    return output


def year_rows(
    year: int,
    output: dict[str, Any],
    *,
    country: str = "us",
    status: str = "succeeded",
) -> BudgetWindowYearRows:
    """Store ``output`` as one year's report run and return its budget rows."""
    stored = economy_result_rows(
        output,
        run_ids=RunIds(
            report_run_id=uuid4(),
            baseline_simulation_run_id=uuid4(),
            reform_simulation_run_id=uuid4(),
        ),
        country=country,
    )
    return BudgetWindowYearRows(
        year=year,
        status=status,
        spm_provenance=stored.report_run_columns["spm_provenance"],
        budget_summary=tuple(
            BudgetSummary(id=uuid4(), **row) for row in stored.rows["budget_summary"]
        ),
    )


def window_rows(
    *years: BudgetWindowYearRows,
    country: str = "us",
    first_year: int | None = 2026,
    window_size: int | None = None,
) -> BudgetWindowResultRows:
    return BudgetWindowResultRows(
        country_id=country,
        first_year=first_year,
        window_size=len(years) if window_size is None else window_size,
        years=years,
    )


def test_each_years_budget_figures_and_their_totals_are_the_window_result() -> None:
    rows = window_rows(
        year_rows(
            2026, year_output("us", tax=1500.0, state_tax=250.0, benefits=-500.0)
        ),
        year_rows(
            2027, year_output("us", tax=1700.0, state_tax=300.0, benefits=-400.0)
        ),
        year_rows(
            2028, year_output("us", tax=1900.0, state_tax=350.0, benefits=-300.0)
        ),
    )

    result = window_transformations.budget_window_result(rows).model_dump(
        mode="json", by_alias=True
    )

    assert result["kind"] == "budgetWindow"
    assert (result["startYear"], result["endYear"], result["windowSize"]) == (
        "2026",
        "2028",
        3,
    )
    first_year = result["annualImpacts"][0]
    assert {
        key: value for key, value in first_year.items() if key != "spm_provenance"
    } == {
        "year": "2026",
        "taxRevenueImpact": 1500.0,
        "federalTaxRevenueImpact": 1250.0,
        "stateTaxRevenueImpact": 250.0,
        "benefitSpendingImpact": -500.0,
        "budgetaryImpact": 2000.0,
    }
    assert [year["year"] for year in result["annualImpacts"]] == [
        "2026",
        "2027",
        "2028",
    ]
    assert result["totals"] == {
        "year": "Total",
        "taxRevenueImpact": 5100.0,
        "federalTaxRevenueImpact": 4200.0,
        "stateTaxRevenueImpact": 900.0,
        "benefitSpendingImpact": -1200.0,
        "budgetaryImpact": 6300.0,
    }


def test_each_year_answers_its_own_spm_receipts_with_package_names_as_keys() -> None:
    output = year_output("us", tax=1.0, state_tax=0.0, benefits=0.0)

    result = window_transformations.budget_window_result(
        window_rows(year_rows(2026, output))
    ).model_dump(mode="json", by_alias=True)

    receipts = result["annualImpacts"][0]["spm_provenance"]
    assert receipts == output["spm_provenance"]
    assert "policyengine-us" in receipts["baseline"]["receipt"]["runtime_versions"]


def test_a_year_without_spm_receipts_answers_null_receipts() -> None:
    output = year_output("uk", tax=4.0e9, state_tax=0.0, benefits=1.0e9)

    result = window_transformations.budget_window_result(
        window_rows(year_rows(2026, output, country="uk"), country="uk")
    ).model_dump(mode="json", by_alias=True)

    assert result["annualImpacts"][0]["spm_provenance"] is None


def test_a_uk_year_has_no_state_tax_so_its_federal_impact_is_all_of_it() -> None:
    output = year_output("uk", tax=4.0e9, state_tax=0.0, benefits=1.0e9)

    result = window_transformations.budget_window_result(
        window_rows(year_rows(2026, output, country="uk"), country="uk")
    ).model_dump(mode="json", by_alias=True)

    assert result["annualImpacts"][0]["stateTaxRevenueImpact"] == 0.0
    assert result["annualImpacts"][0]["federalTaxRevenueImpact"] == 4.0e9


def test_totals_are_summed_exactly_as_decimals() -> None:
    # As floats, 0.1 + 0.2 is 0.30000000000000004; the old gateway sums the
    # shortest decimal form of each figure.
    rows = window_rows(
        year_rows(2026, year_output("us", tax=0.1, state_tax=0.0, benefits=0.0)),
        year_rows(2027, year_output("us", tax=0.2, state_tax=0.0, benefits=0.0)),
    )

    totals = window_transformations.budget_window_result(rows).model_dump(
        mode="json", by_alias=True
    )["totals"]

    assert totals["taxRevenueImpact"] == 0.3
    assert totals["budgetaryImpact"] == 0.3


def test_years_are_answered_in_year_order_whatever_order_they_are_read_in() -> None:
    rows = window_rows(
        year_rows(2027, year_output("us", tax=2.0, state_tax=0.0, benefits=0.0)),
        year_rows(2026, year_output("us", tax=1.0, state_tax=0.0, benefits=0.0)),
    )

    result = window_transformations.budget_window_result(rows).model_dump(
        mode="json", by_alias=True
    )

    assert [year["year"] for year in result["annualImpacts"]] == ["2026", "2027"]
    assert [year["taxRevenueImpact"] for year in result["annualImpacts"]] == [1.0, 2.0]


def one_year() -> BudgetWindowYearRows:
    return year_rows(2026, year_output("us", tax=1.0, state_tax=0.0, benefits=0.0))


def without_household_tax(year: BudgetWindowYearRows) -> BudgetWindowYearRows:
    return BudgetWindowYearRows(
        year=year.year,
        status=year.status,
        spm_provenance=year.spm_provenance,
        budget_summary=tuple(
            row for row in year.budget_summary if row.variable_name != "household_tax"
        ),
    )


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        pytest.param(
            window_rows(one_year(), window_size=2),
            "has no 2027 report run",
            id="missing-year",
        ),
        pytest.param(
            window_rows(
                one_year(),
                year_rows(
                    2028, year_output("us", tax=1.0, state_tax=0.0, benefits=0.0)
                ),
            ),
            "has no 2027 report run",
            id="gap",
        ),
        pytest.param(
            window_rows(
                one_year(),
                year_rows(
                    2027, year_output("us", tax=1.0, state_tax=0.0, benefits=0.0)
                ),
                window_size=1,
            ),
            "has a report run for 2027, outside the window",
            id="year-outside-the-window",
        ),
        pytest.param(
            window_rows(
                year_rows(
                    2026,
                    year_output("us", tax=1.0, state_tax=0.0, benefits=0.0),
                    status="failed",
                )
            ),
            "2026 report run has not succeeded",
            id="year-not-succeeded",
        ),
        pytest.param(
            window_rows(one_year(), first_year=None),
            "stores no first year",
            id="no-year",
        ),
        pytest.param(
            window_rows(without_household_tax(one_year())),
            "2026: the budget summary has no household_tax row",
            id="year-without-a-budget-figure",
        ),
    ],
)
def test_a_window_whose_years_cannot_give_the_result_is_unreadable(
    rows: BudgetWindowResultRows, reason: str
) -> None:
    with pytest.raises(BudgetWindowResultUnreadableError, match=reason):
        window_transformations.budget_window_result(rows)


def test_a_year_whose_spm_receipts_are_of_another_shape_is_unreadable() -> None:
    year = one_year()
    malformed = BudgetWindowYearRows(
        year=year.year,
        status=year.status,
        spm_provenance={"schema_version": "unknown"},
        budget_summary=year.budget_summary,
    )

    with pytest.raises(
        BudgetWindowResultUnreadableError, match="2026: the report run's SPM"
    ):
        window_transformations.budget_window_result(window_rows(malformed))
