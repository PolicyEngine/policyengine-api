"""The budget-window result the years of a budget-window run hold.

A budget-window report compares its baseline and reform simulations in each
year of a window of consecutive years. Each calculation of it is a
``budget_window_runs`` row, and each year of that calculation a report run
naming the row and its year; the simulation service's Modal workers store
each year's economy result as that report run's rows.

``BudgetWindowResult`` has the fields of the simulation service's
``BudgetWindowResult`` (``policyengine_simulation_contract.gateway_models``),
the budget-window format the app reads today: each year's budget figures, in
year order, and their totals. Its keys are camelCase, apart from each year's
``spm_provenance``. ``BudgetWindowResultRows`` holds what one window run's
years store for it, and ``budget_window_results.transformations`` builds the
result from them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from policyengine_api.spm import SPMComparisonProvenance

if TYPE_CHECKING:
    from pydantic import JsonValue

    from policyengine_api.data.v2.models import BudgetSummary as BudgetSummaryRow


class BudgetWindowResultUnreadableError(ValueError):
    """A succeeded budget-window run's years cannot give the window's result.

    A year of the window has no report run, or one that has not succeeded,
    or its rows lack a budget figure every result has. The message names
    what is missing, never a row's values.
    """


class BudgetWindowResultModel(BaseModel):
    """Base of the budget-window result's parts: closed, immutable, camelCase."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        alias_generator=to_camel,
        serialize_by_alias=True,
        validate_by_name=True,
    )


class BudgetWindowAnnualImpact(BudgetWindowResultModel):
    """One year's budget figures; ``year`` is the year as text, such as "2026".

    Impacts are reform minus baseline totals in the country's currency.
    ``state_tax_revenue_impact`` is US state income tax (0 for the UK), and
    ``federal_tax_revenue_impact`` the rest of ``tax_revenue_impact``.
    ``budgetary_impact`` is ``tax_revenue_impact`` minus
    ``benefit_spending_impact``. ``spm_provenance`` is the SPM receipts of
    that year's report run, or null without any.
    """

    spm_provenance: SPMComparisonProvenance | None = Field(alias="spm_provenance")
    year: str
    tax_revenue_impact: float
    federal_tax_revenue_impact: float
    state_tax_revenue_impact: float
    benefit_spending_impact: float
    budgetary_impact: float


class BudgetWindowTotals(BudgetWindowResultModel):
    """The sums of every year's budget figures, summed as exact decimals."""

    year: Literal["Total"] = "Total"
    tax_revenue_impact: float
    federal_tax_revenue_impact: float
    state_tax_revenue_impact: float
    benefit_spending_impact: float
    budgetary_impact: float


class BudgetWindowResult(BudgetWindowResultModel):
    """Today's budget-window format: each year's figures, in year order, and totals.

    ``start_year`` and ``end_year`` are the window's first and last years, as
    text, and ``window_size`` its number of years.
    """

    kind: Literal["budgetWindow"] = "budgetWindow"
    start_year: str
    end_year: str
    window_size: int
    annual_impacts: tuple[BudgetWindowAnnualImpact, ...]
    totals: BudgetWindowTotals


@dataclass(frozen=True)
class BudgetWindowYearRows:
    """What one year's report run stores for the window's result.

    ``status`` is the report run's status, ``spm_provenance`` its stored SPM
    receipts, and ``budget_summary`` its budget summary rows.
    """

    year: int
    status: str
    spm_provenance: dict[str, JsonValue] | None
    budget_summary: tuple[BudgetSummaryRow, ...]


@dataclass(frozen=True)
class BudgetWindowResultRows:
    """A window run's years, and the window they should cover.

    The window is ``window_size`` years from ``first_year``, the report's
    ``year`` and ``budget_window_size``; either is None when the report row
    stores none. ``years`` may come in any order.
    """

    country_id: str
    first_year: int | None
    window_size: int | None
    years: tuple[BudgetWindowYearRows, ...]
