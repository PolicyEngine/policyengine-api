"""Rebuild a report run's economy result from its result rows.

This reverses the simulation service's writer
(``policyengine_stage12_persistence.report_run_results``), part by part:

- ``budget`` from ``budget_summary``'s household totals: the tax, benefit and
  US state income tax changes, the baseline net income and the household
  count. ``budgetary_impact`` is tax minus benefits, and a country with no
  state income tax row reports 0.
- ``detailed_budget`` from ``program_statistics``, one program per row.
- ``decile`` and ``wealth_decile`` from ``decile_impacts``: income deciles
  name no ranking variable, wealth deciles ``household_wealth_decile``. The
  rows hold relative changes as percentages, the result as fractions.
- ``intra_decile`` and ``intra_wealth_decile`` from ``intra_decile_impacts``,
  deciles 1 to 10; each category's ``all`` is the mean of its deciles.
- ``poverty``, ``poverty_by_gender`` and ``poverty_by_race`` from each
  simulation run's ``poverty`` rows, and ``inequality`` from its
  ``inequality`` row: the baseline value from the baseline run's row, the
  reform value from the reform run's.
- ``labor_supply_response`` from ``labor_supply_responses`` and
  ``labor_supply_decile_responses``.
- ``congressional_district_impact``, ``constituency_impact`` and
  ``local_authority_impact`` from their tables, in district or area code
  order.
- ``cliff_impact``, ``spm_provenance``, ``data_version`` and
  ``model_version`` from the report run's own columns; the SPM receipts are
  read as ``SPMComparisonProvenance``.

An optional part with no rows is null. The writer stores no rows for an empty
list either, so a UK result whose areas were all withheld reads back with
null areas, and a UK wealth breakdown without deciles as no breakdown.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from policyengine_api.services.v2.stored_reports.economy_results.types import (
    AgePoverty,
    BaselineReformValue,
    BudgetaryImpact,
    CliffImpact,
    CliffImpactInSimulation,
    CongressionalDistrictImpact,
    CongressionalDistrictImpacts,
    ConstituencyImpact,
    DecileChange,
    EconomyResult,
    EconomyResultUnreadableError,
    GenderPoverty,
    InequalityChange,
    IntraDecileShares,
    LaborSupplyDeciles,
    LaborSupplyDecileValues,
    LaborSupplyHours,
    LaborSupplyRelativeResponse,
    LaborSupplyResponse,
    LocalAuthorityImpact,
    PovertyByAge,
    PovertyByGender,
    PovertyByRace,
    ProgramBudget,
    RacePoverty,
)
from policyengine_api.spm import SPMComparisonProvenance

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from uuid import UUID

    from pydantic import JsonValue

    from policyengine_api.data.v2.models import (
        CongressionalDistrictImpact as CongressionalDistrictImpactRow,
    )
    from policyengine_api.data.v2.models import DecileImpact as DecileImpactRow
    from policyengine_api.data.v2.models import (
        IntraDecileImpact as IntraDecileImpactRow,
    )
    from policyengine_api.data.v2.models import Poverty as PovertyRow
    from policyengine_api.services.v2.stored_reports.economy_results.types import (
        EconomyResultRows,
        ReportRunResultColumns,
    )

# .py's poverty types behind the result's "poverty" and "deep_poverty".
POVERTY_TYPES = {
    "us": {"poverty": "spm", "deep_poverty": "spm_deep"},
    "uk": {"poverty": "relative_bhc", "deep_poverty": "absolute_bhc"},
}
# The income each country's inequality measures rank households by.
INEQUALITY_INCOME_VARIABLES = {
    "us": "household_net_income",
    "uk": "equiv_hbai_household_net_income",
}
RACE_GROUPS = ("white", "black", "hispanic", "other")
WEALTH_DECILE_VARIABLE = "household_wealth_decile"
INTRA_DECILE_COLUMNS = {
    "Lose more than 5%": "lose_more_than_5pct",
    "Lose less than 5%": "lose_less_than_5pct",
    "No change": "no_change",
    "Gain less than 5%": "gain_less_than_5pct",
    "Gain more than 5%": "gain_more_than_5pct",
}
STATE_INCOME_TAX_VARIABLE = "household_state_income_tax"
# The Census FIPS code of each state and the District of Columbia, which a
# district row stores in place of the state's abbreviation.
US_STATE_ABBREVIATIONS_BY_FIPS = {
    1: "AL",
    2: "AK",
    4: "AZ",
    5: "AR",
    6: "CA",
    8: "CO",
    9: "CT",
    10: "DE",
    11: "DC",
    12: "FL",
    13: "GA",
    15: "HI",
    16: "ID",
    17: "IL",
    18: "IN",
    19: "IA",
    20: "KS",
    21: "KY",
    22: "LA",
    23: "ME",
    24: "MD",
    25: "MA",
    26: "MI",
    27: "MN",
    28: "MS",
    29: "MO",
    30: "MT",
    31: "NE",
    32: "NV",
    33: "NH",
    34: "NJ",
    35: "NM",
    36: "NY",
    37: "NC",
    38: "ND",
    39: "OH",
    40: "OK",
    41: "OR",
    42: "PA",
    44: "RI",
    45: "SC",
    46: "SD",
    47: "TN",
    48: "TX",
    49: "UT",
    50: "VT",
    51: "VA",
    53: "WA",
    54: "WV",
    55: "WI",
    56: "WY",
}
DISCLOSURE_FIELDS = (
    "disclosure_tier",
    "average_household_income_change_lower",
    "average_household_income_change_upper",
    "relative_household_income_change_lower",
    "relative_household_income_change_upper",
)
Side = Literal["baseline", "reform"]


def _figure(value: float | None, *, name: str) -> float:
    """Return a stored figure every result has, or raise if the row holds none."""
    if value is None:
        msg = f"the stored {name} is null"
        raise EconomyResultUnreadableError(msg)
    return value


def _spm_provenance(
    stored: dict[str, JsonValue] | None,
) -> SPMComparisonProvenance | None:
    """Return the report run's stored SPM receipts, or None without any.

    Raise EconomyResultUnreadableError for receipts of another shape, such as
    a baseline and reform whose receipts differ.
    """
    if stored is None:
        return None
    try:
        return SPMComparisonProvenance.model_validate(stored)
    except ValidationError as error:
        msg = "the report run's SPM receipts are of another shape"
        raise EconomyResultUnreadableError(msg) from error


def economy_result(rows: EconomyResultRows) -> EconomyResult:
    """Return the economy result ``rows`` hold.

    Raise EconomyResultUnreadableError when the rows lack a part every
    economy result has, the stored SPM receipts are of another shape, or the
    country has no known poverty measures.
    """
    country_id = rows.country_id
    if country_id not in POVERTY_TYPES:
        msg = f"no poverty measures are known for country {country_id!r}"
        raise EconomyResultUnreadableError(msg)
    report_run = rows.report_run
    if report_run.data_version is None:
        msg = "the report run stores no data version"
        raise EconomyResultUnreadableError(msg)
    poverty = _PovertyRates(rows)
    income_deciles, wealth_deciles = _decile_rows_by_type(rows.decile_impacts)
    if not income_deciles:
        msg = "the result has no income decile rows"
        raise EconomyResultUnreadableError(msg)
    has_wealth_shares = any(
        row.decile_type == "wealth" for row in rows.intra_decile_impacts
    )
    return EconomyResult(
        spm_provenance=_spm_provenance(report_run.spm_provenance),
        model_version=report_run.country_package_version,
        data_version=report_run.data_version,
        budget=_budget(rows),
        detailed_budget=_detailed_budget(rows),
        decile=_deciles(income_deciles),
        inequality=_inequality(rows),
        poverty=PovertyByAge(
            poverty=poverty.by_age("poverty"),
            deep_poverty=poverty.by_age("deep_poverty"),
        ),
        poverty_by_gender=PovertyByGender(
            poverty=poverty.by_gender("poverty"),
            deep_poverty=poverty.by_gender("deep_poverty"),
        ),
        poverty_by_race=poverty.by_race(),
        intra_decile=_intra_decile(rows.intra_decile_impacts, "income"),
        wealth_decile=_deciles(wealth_deciles) if wealth_deciles else None,
        intra_wealth_decile=(
            _intra_decile(rows.intra_decile_impacts, "wealth")
            if has_wealth_shares
            else None
        ),
        labor_supply_response=_labor_supply_response(rows),
        constituency_impact=_constituencies(rows),
        local_authority_impact=_local_authorities(rows),
        congressional_district_impact=_districts(rows.congressional_district_impacts),
        cliff_impact=_cliff_impact(report_run),
    )


def _budget(rows: EconomyResultRows) -> BudgetaryImpact:
    household_totals = {
        row.variable_name: row
        for row in rows.budget_summary
        if row.entity == "household"
    }

    def figure(variable: str, column: Literal["change", "baseline_total"]) -> float:
        row = household_totals.get(variable)
        if row is None:
            msg = f"the budget summary has no {variable} row"
            raise EconomyResultUnreadableError(msg)
        return _figure(getattr(row, column), name=f"{variable} {column}")

    tax = figure("household_tax", "change")
    benefits = figure("household_benefits", "change")
    state_income_tax = (
        figure(STATE_INCOME_TAX_VARIABLE, "change")
        if rows.country_id == "us" or STATE_INCOME_TAX_VARIABLE in household_totals
        else 0.0
    )
    return BudgetaryImpact(
        tax_revenue_impact=tax,
        state_tax_revenue_impact=state_income_tax,
        benefit_spending_impact=benefits,
        budgetary_impact=tax - benefits,
        households=figure("household_weight", "baseline_total"),
        baseline_net_income=figure("household_net_income", "baseline_total"),
    )


def _detailed_budget(rows: EconomyResultRows) -> dict[str, ProgramBudget]:
    return {
        row.program_name: ProgramBudget(
            baseline=_figure(row.baseline_total, name=f"{row.program_name} baseline"),
            reform=_figure(row.reform_total, name=f"{row.program_name} reform"),
            difference=_figure(row.change, name=f"{row.program_name} change"),
            is_tax=row.is_tax,
        )
        for row in sorted(rows.program_statistics, key=lambda row: row.program_name)
    }


def _decile_rows_by_type(
    decile_rows: Iterable[DecileImpactRow],
) -> tuple[list[DecileImpactRow], list[DecileImpactRow]]:
    """Return household net income's income-decile rows and wealth-decile rows."""
    income: list[DecileImpactRow] = []
    wealth: list[DecileImpactRow] = []
    for row in sorted(decile_rows, key=lambda row: row.decile):
        if row.income_variable != "household_net_income" or row.entity != "household":
            continue
        if row.decile_variable is None:
            income.append(row)
        elif row.decile_variable == WEALTH_DECILE_VARIABLE:
            wealth.append(row)
    return income, wealth


def _deciles(decile_rows: Sequence[DecileImpactRow]) -> DecileChange:
    return DecileChange(
        average={
            str(row.decile): _figure(row.absolute_change, name="decile change")
            for row in decile_rows
        },
        relative={
            str(row.decile): (
                _figure(row.relative_change, name="relative decile change") / 100
            )
            for row in decile_rows
        },
    )


def _intra_decile(
    shares: Iterable[IntraDecileImpactRow], decile_type: str
) -> IntraDecileShares:
    """Return each category's share by decile, and its mean over the deciles.

    Every category is listed, as the simulation service lists them, with no
    shares when the rows hold none.
    """
    decile_rows = sorted(
        (row for row in shares if row.decile_type == decile_type and row.decile > 0),
        key=lambda row: row.decile,
    )
    deciles: dict[str, list[float]] = {}
    for label, column in INTRA_DECILE_COLUMNS.items():
        values = [getattr(row, column) for row in decile_rows]
        deciles[label] = [value for value in values if value is not None]
    return IntraDecileShares(
        deciles=deciles,
        all={
            label: sum(values) / len(values) if values else 0.0
            for label, values in deciles.items()
        },
    )


class _PovertyRates:
    """Each simulation run's poverty rates, by measure and group."""

    def __init__(self, rows: EconomyResultRows) -> None:
        self._poverty_types = POVERTY_TYPES[rows.country_id]
        self._run_ids: dict[Side, UUID] = {
            "baseline": rows.baseline_simulation_run_id,
            "reform": rows.reform_simulation_run_id,
        }
        self._rates: dict[tuple[UUID, str, str | None, str | None], PovertyRow] = {
            (
                row.simulation_run_id,
                row.poverty_type,
                row.filter_variable,
                row.filter_group,
            ): row
            for row in rows.poverty
            if row.entity == "person"
        }

    def has_rate(self, measure: str, filter_variable: str, filter_group: str) -> bool:
        """Return whether either run has the measure's rate for the group."""
        poverty_type = self._poverty_types[measure]
        return any(
            (run_id, poverty_type, filter_variable, filter_group) in self._rates
            for run_id in self._run_ids.values()
        )

    def rate(
        self, measure: str, filter_variable: str | None, filter_group: str | None
    ) -> BaselineReformValue:
        """Return both runs' rates, or raise if either run has none."""
        poverty_type = self._poverty_types[measure]
        values: dict[str, float] = {}
        for side, run_id in self._run_ids.items():
            row = self._rates.get((run_id, poverty_type, filter_variable, filter_group))
            if row is None:
                group = filter_group or "everyone"
                msg = f"the {side} run has no {poverty_type} poverty rate for {group}"
                raise EconomyResultUnreadableError(msg)
            values[side] = _figure(row.rate, name=f"{poverty_type} poverty rate")
        return BaselineReformValue(**values)

    def by_age(self, measure: str) -> AgePoverty:
        return AgePoverty(
            child=self.rate(measure, "age", "child"),
            adult=self.rate(measure, "age", "adult"),
            senior=self.rate(measure, "age", "senior"),
            all=self.rate(measure, None, None),
        )

    def by_gender(self, measure: str) -> GenderPoverty:
        return GenderPoverty(
            male=self.rate(measure, "is_male", "male"),
            female=self.rate(measure, "is_male", "female"),
        )

    def by_race(self) -> PovertyByRace | None:
        """Return poverty by race, or None when no run has a race breakdown."""
        if not any(self.has_rate("poverty", "race", group) for group in RACE_GROUPS):
            return None
        return PovertyByRace(
            poverty=RacePoverty(
                white=self.rate("poverty", "race", "white"),
                black=self.rate("poverty", "race", "black"),
                hispanic=self.rate("poverty", "race", "hispanic"),
                other=self.rate("poverty", "race", "other"),
            )
        )


def _inequality(rows: EconomyResultRows) -> InequalityChange:
    income_variable = INEQUALITY_INCOME_VARIABLES[rows.country_id]
    by_run = {
        row.simulation_run_id: row
        for row in rows.inequality
        if row.income_variable == income_variable and row.entity == "household"
    }
    measures: dict[str, dict[str, float]] = {
        "gini": {},
        "top_10_pct_share": {},
        "top_1_pct_share": {},
    }
    for side, run_id in (
        ("baseline", rows.baseline_simulation_run_id),
        ("reform", rows.reform_simulation_run_id),
    ):
        row = by_run.get(run_id)
        if row is None:
            msg = f"the {side} run has no inequality row"
            raise EconomyResultUnreadableError(msg)
        measures["gini"][side] = _figure(row.gini, name="gini")
        measures["top_10_pct_share"][side] = _figure(
            row.top_10_share, name="top 10% share"
        )
        measures["top_1_pct_share"][side] = _figure(
            row.top_1_share, name="top 1% share"
        )
    return InequalityChange(
        gini=BaselineReformValue(**measures["gini"]),
        top_10_pct_share=BaselineReformValue(**measures["top_10_pct_share"]),
        top_1_pct_share=BaselineReformValue(**measures["top_1_pct_share"]),
    )


def _labor_supply_response(rows: EconomyResultRows) -> LaborSupplyResponse | None:
    if not rows.labor_supply_responses:
        return None
    response = rows.labor_supply_responses[0]
    deciles = sorted(rows.labor_supply_decile_responses, key=lambda row: row.decile)

    def by_decile(column: str) -> dict[int, float]:
        return {
            row.decile: getattr(row, column)
            for row in deciles
            if getattr(row, column) is not None
        }

    return LaborSupplyResponse(
        substitution_lsr=response.substitution_effect_earnings_change,
        income_lsr=response.income_effect_earnings_change,
        relative_lsr=LaborSupplyRelativeResponse(
            income=response.relative_income_effect,
            substitution=response.relative_substitution_effect,
        ),
        total_change=response.total_earnings_change,
        revenue_change=response.revenue_change,
        decile=LaborSupplyDeciles(
            average=LaborSupplyDecileValues(
                income=by_decile("average_income_effect"),
                substitution=by_decile("average_substitution_effect"),
            ),
            relative=LaborSupplyDecileValues(
                income=by_decile("relative_income_effect"),
                substitution=by_decile("relative_substitution_effect"),
            ),
        ),
        hours=LaborSupplyHours(
            baseline=response.baseline_weekly_hours,
            reform=response.reform_weekly_hours,
            change=response.weekly_hours_change,
            income_effect=response.weekly_hours_income_effect,
            substitution_effect=response.weekly_hours_substitution_effect,
        ),
    )


def _area_values(row: object) -> dict[str, Any]:
    """Return a UK area row's income changes, population and disclosure fields."""
    return {
        field: getattr(row, field)
        for field in (
            "average_household_income_change",
            "relative_household_income_change",
            "population",
            *DISCLOSURE_FIELDS,
        )
    }


def _constituencies(rows: EconomyResultRows) -> list[ConstituencyImpact] | None:
    if not rows.constituency_impacts:
        return None
    return [
        ConstituencyImpact(
            constituency_code=row.constituency_code,
            constituency_name=row.constituency_name,
            **_area_values(row),
        )
        for row in sorted(
            rows.constituency_impacts, key=lambda row: row.constituency_code
        )
    ]


def _local_authorities(rows: EconomyResultRows) -> list[LocalAuthorityImpact] | None:
    if not rows.local_authority_impacts:
        return None
    return [
        LocalAuthorityImpact(
            local_authority_code=row.local_authority_code,
            local_authority_name=row.local_authority_name,
            **_area_values(row),
        )
        for row in sorted(
            rows.local_authority_impacts, key=lambda row: row.local_authority_code
        )
    ]


def _district_name(row: CongressionalDistrictImpactRow) -> str:
    """Return the district as ``ST-NN``; an at-large district (number 0) is ``01``."""
    state = US_STATE_ABBREVIATIONS_BY_FIPS.get(row.state_fips)
    if state is None:
        msg = f"a congressional district names unknown state FIPS {row.state_fips}"
        raise EconomyResultUnreadableError(msg)
    number = 1 if row.district_number == 0 else row.district_number
    return f"{state}-{number:02d}"


def _districts(
    district_rows: Sequence[CongressionalDistrictImpactRow],
) -> CongressionalDistrictImpacts | None:
    if not district_rows:
        return None
    return CongressionalDistrictImpacts(
        districts=[
            CongressionalDistrictImpact(
                district=_district_name(row),
                average_household_income_change=row.average_household_income_change,
                relative_household_income_change=row.relative_household_income_change,
                winner_percentage=row.winner_percentage,
                loser_percentage=row.loser_percentage,
                no_change_percentage=row.no_change_percentage,
                population=row.population,
            )
            for row in sorted(district_rows, key=lambda row: row.district_geoid)
        ]
    )


def _cliff_impact(report_run: ReportRunResultColumns) -> CliffImpact | None:
    """Return the cliff impact, or None when the run stores none.

    The database keeps the four columns all set or all null.
    """
    if (
        report_run.baseline_cliff_gap is None
        or report_run.baseline_cliff_share is None
        or report_run.reform_cliff_gap is None
        or report_run.reform_cliff_share is None
    ):
        return None
    return CliffImpact(
        baseline=CliffImpactInSimulation(
            cliff_gap=report_run.baseline_cliff_gap,
            cliff_share=report_run.baseline_cliff_share,
        ),
        reform=CliffImpactInSimulation(
            cliff_gap=report_run.reform_cliff_gap,
            cliff_share=report_run.reform_cliff_share,
        ),
    )
