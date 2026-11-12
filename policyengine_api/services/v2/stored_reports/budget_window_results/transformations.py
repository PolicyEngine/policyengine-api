"""Rebuild a budget window's result from the budget rows of its years.

Each year's figures are its report run's budget figures, read from its budget
summary rows as an economy result's ``budget`` is
(``economy_results.transformations.budget_impact``):
``federal_tax_revenue_impact`` is the tax revenue impact less the US state
income tax impact, which is 0 for the UK. Each year carries its own report
run's SPM receipts. The totals sum each figure as the exact decimal of its
shortest text form, as the old simulation gateway's
``budget_window_results.sum_annual_impacts`` does, so a long window's totals
do not gather binary rounding errors.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import ReportRunStatus
from policyengine_api.services.v2.stored_reports.budget_window_results.types import (
    BudgetWindowAnnualImpact,
    BudgetWindowResult,
    BudgetWindowResultRows,
    BudgetWindowResultUnreadableError,
    BudgetWindowTotals,
    BudgetWindowYearRows,
)
from policyengine_api.services.v2.stored_reports.economy_results import (
    transformations as economy_transformations,
)
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResultUnreadableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


def budget_window_result(rows: BudgetWindowResultRows) -> BudgetWindowResult:
    """Return the budget-window result ``rows`` hold.

    Raise BudgetWindowResultUnreadableError when the report stores no
    window, a year of the window has no report run or one that has not
    succeeded, a report run is of a year outside the window, or a year's rows
    lack a budget figure or hold SPM receipts of another shape.
    """
    years = _window_years(rows)
    annual_impacts = tuple(
        _annual_impact(rows.country_id, year_rows) for year_rows in years
    )
    first_year = years[0].year
    return BudgetWindowResult(
        start_year=str(first_year),
        end_year=str(years[-1].year),
        window_size=len(years),
        annual_impacts=annual_impacts,
        totals=_totals(annual_impacts),
    )


def _window_years(rows: BudgetWindowResultRows) -> Sequence[BudgetWindowYearRows]:
    """Return one succeeded year per year of the window, in year order."""
    if rows.first_year is None or rows.window_size is None:
        msg = "the report stores no first year or window size"
        raise BudgetWindowResultUnreadableError(msg)
    window = range(rows.first_year, rows.first_year + rows.window_size)
    by_year = {year_rows.year: year_rows for year_rows in rows.years}
    years = []
    for year in window:
        year_rows = by_year.get(year)
        if year_rows is None:
            msg = f"the window has no {year} report run"
            raise BudgetWindowResultUnreadableError(msg)
        if year_rows.status is not ReportRunStatus.SUCCEEDED:
            msg = f"the window's {year} report run has not succeeded"
            raise BudgetWindowResultUnreadableError(msg)
        years.append(year_rows)
    for year in sorted(set(by_year) - set(window)):
        msg = f"the window has a report run for {year}, outside the window"
        raise BudgetWindowResultUnreadableError(msg)
    return years


def _annual_impact(
    country_id: str, year_rows: BudgetWindowYearRows
) -> BudgetWindowAnnualImpact:
    try:
        budget = economy_transformations.budget_impact(
            country_id=country_id, budget_summary=year_rows.budget_summary
        )
        spm_provenance = economy_transformations.stored_spm_provenance(
            year_rows.spm_provenance
        )
    except EconomyResultUnreadableError as error:
        msg = f"{year_rows.year}: {error}"
        raise BudgetWindowResultUnreadableError(msg) from error
    return BudgetWindowAnnualImpact(
        spm_provenance=spm_provenance,
        year=str(year_rows.year),
        tax_revenue_impact=budget.tax_revenue_impact,
        federal_tax_revenue_impact=(
            budget.tax_revenue_impact - budget.state_tax_revenue_impact
        ),
        state_tax_revenue_impact=budget.state_tax_revenue_impact,
        benefit_spending_impact=budget.benefit_spending_impact,
        budgetary_impact=budget.budgetary_impact,
    )


def _total(
    annual_impacts: Sequence[BudgetWindowAnnualImpact],
    figure: Callable[[BudgetWindowAnnualImpact], float],
) -> float:
    """Sum one figure of every year as exact decimals."""
    return float(
        sum(
            (Decimal(str(figure(impact))) for impact in annual_impacts),
            Decimal(0),
        )
    )


def _totals(annual_impacts: Sequence[BudgetWindowAnnualImpact]) -> BudgetWindowTotals:
    return BudgetWindowTotals(
        tax_revenue_impact=_total(
            annual_impacts, lambda impact: impact.tax_revenue_impact
        ),
        federal_tax_revenue_impact=_total(
            annual_impacts, lambda impact: impact.federal_tax_revenue_impact
        ),
        state_tax_revenue_impact=_total(
            annual_impacts, lambda impact: impact.state_tax_revenue_impact
        ),
        benefit_spending_impact=_total(
            annual_impacts, lambda impact: impact.benefit_spending_impact
        ),
        budgetary_impact=_total(annual_impacts, lambda impact: impact.budgetary_impact),
    )
