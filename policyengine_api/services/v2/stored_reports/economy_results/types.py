"""The single-year economy result a report run's result rows hold.

``EconomyResult`` has the fields and nesting of the simulation service's
``SingleYearMacroOutput`` (``policyengine_simulation_contract.macro_output``),
the result format the app reads today. The simulation service's Modal workers
store each result as rows of the result tables
(``policyengine_stage12_persistence.report_run_results``);
``EconomyResultRows`` holds the rows of one report run, and
``economy_results.transformations`` builds the result from them again.

A local-area report's result (a UK-wide or nation report on the dataset the
catalog version gives local areas) also lists the codes of the areas
disclosure control withheld at each level, from ``withheld_area_codes``, as
``SingleYearMacroOutput``'s ``constituency_withheld_codes`` and
``local_authority_withheld_codes`` do; every other result leaves the two
lists out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from policyengine_api.spm import SPMComparisonProvenance

if TYPE_CHECKING:
    from uuid import UUID

    # The tables' models, named apart from the result parts they hold.
    from policyengine_api.data.v2.models import BudgetSummary as BudgetSummaryRow
    from policyengine_api.data.v2.models import (
        CongressionalDistrictImpact as CongressionalDistrictImpactRow,
    )
    from policyengine_api.data.v2.models import (
        ConstituencyImpact as ConstituencyImpactRow,
    )
    from policyengine_api.data.v2.models import DecileImpact as DecileImpactRow
    from policyengine_api.data.v2.models import Inequality as InequalityRow
    from policyengine_api.data.v2.models import (
        IntraDecileImpact as IntraDecileImpactRow,
    )
    from policyengine_api.data.v2.models import (
        LaborSupplyDecileResponse as LaborSupplyDecileResponseRow,
    )
    from policyengine_api.data.v2.models import (
        LaborSupplyResponse as LaborSupplyResponseRow,
    )
    from policyengine_api.data.v2.models import (
        LocalAuthorityImpact as LocalAuthorityImpactRow,
    )
    from policyengine_api.data.v2.models import Poverty as PovertyRow
    from policyengine_api.data.v2.models import (
        ProgramStatistics as ProgramStatisticsRow,
    )
    from policyengine_api.data.v2.models import (
        WithheldAreaCode as WithheldAreaCodeRow,
    )


class EconomyResultUnreadableError(ValueError):
    """A succeeded report run's rows lack a part every economy result has.

    The message names the missing part, never a row's values.
    """


class EconomyResultModel(BaseModel):
    """Base of the economy result's parts: closed, immutable objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BudgetaryImpact(EconomyResultModel):
    """The reform's headline budget effect in the simulated year.

    Impacts are reform minus baseline totals in the country's currency;
    ``budgetary_impact`` is ``tax_revenue_impact`` minus
    ``benefit_spending_impact``, and ``state_tax_revenue_impact`` is US state
    income tax (0 for the UK). ``households`` is the weighted number of
    households and ``baseline_net_income`` their total baseline net income.
    """

    tax_revenue_impact: float
    state_tax_revenue_impact: float
    benefit_spending_impact: float
    budgetary_impact: float
    households: float
    baseline_net_income: float


class ProgramBudget(EconomyResultModel):
    """One program's baseline and reform totals, and reform minus baseline.

    ``is_tax`` says whether the program is a tax or a benefit, and is null for
    results stored before the flag was recorded.
    """

    baseline: float
    reform: float
    difference: float
    is_tax: bool | None


class DecileChange(EconomyResultModel):
    """The change in average household net income in each decile, ``"1"`` to ``"10"``.

    ``average`` is the absolute change and ``relative`` the change as a
    fraction of the decile's baseline average.
    """

    average: dict[str, float]
    relative: dict[str, float]


class IntraDecileShares(EconomyResultModel):
    """Shares of people in each decile who gain or lose, by size of the change.

    ``deciles`` lists each category's share for deciles 1 to 10 in order, and
    ``all`` is each category's mean over those deciles.
    """

    deciles: dict[str, list[float]]
    all: dict[str, float]


class BaselineReformValue(EconomyResultModel):
    """A measure's value under the baseline and under the reform."""

    baseline: float
    reform: float


class AgePoverty(EconomyResultModel):
    """Poverty rates for children, adults, seniors and everyone."""

    child: BaselineReformValue
    adult: BaselineReformValue
    senior: BaselineReformValue
    all: BaselineReformValue


class GenderPoverty(EconomyResultModel):
    """Poverty rates for males and females."""

    male: BaselineReformValue
    female: BaselineReformValue


class RacePoverty(EconomyResultModel):
    """US poverty rates by race and ethnicity."""

    white: BaselineReformValue
    black: BaselineReformValue
    hispanic: BaselineReformValue
    other: BaselineReformValue


class PovertyByAge(EconomyResultModel):
    """Poverty and deep poverty rates by age group.

    In the US these are the SPM poverty and deep SPM poverty rates; in the UK,
    relative and absolute poverty before housing costs.
    """

    poverty: AgePoverty
    deep_poverty: AgePoverty


class PovertyByGender(EconomyResultModel):
    """Poverty and deep poverty rates by gender."""

    poverty: GenderPoverty
    deep_poverty: GenderPoverty


class PovertyByRace(EconomyResultModel):
    """US poverty rates by race; there is no deep poverty breakdown."""

    poverty: RacePoverty


class InequalityChange(EconomyResultModel):
    """The Gini coefficient and the top 10% and top 1% income shares."""

    gini: BaselineReformValue
    top_10_pct_share: BaselineReformValue
    top_1_pct_share: BaselineReformValue


class LaborSupplyRelativeResponse(EconomyResultModel):
    """Income- and substitution-effect responses relative to baseline earnings."""

    income: float
    substitution: float


class LaborSupplyDecileValues(EconomyResultModel):
    """Income- and substitution-effect responses by income decile number."""

    income: dict[int, float]
    substitution: dict[int, float]


class LaborSupplyDeciles(EconomyResultModel):
    """Labour supply responses by decile: per household, and relative to earnings."""

    average: LaborSupplyDecileValues
    relative: LaborSupplyDecileValues


class LaborSupplyHours(EconomyResultModel):
    """Total weekly hours under the baseline and reform, and the change's effects."""

    baseline: float
    reform: float
    change: float
    income_effect: float
    substitution_effect: float


class LaborSupplyResponse(EconomyResultModel):
    """The behavioural labour supply response to the reform.

    ``income_lsr`` and ``substitution_lsr`` are the earnings changes from the
    two effects, and ``total_change`` their sum.
    """

    substitution_lsr: float
    income_lsr: float
    relative_lsr: LaborSupplyRelativeResponse
    total_change: float
    revenue_change: float
    decile: LaborSupplyDeciles
    hours: LaborSupplyHours


class CliffImpactInSimulation(EconomyResultModel):
    """Net income lost to a small earnings rise, and the share of adults on a cliff."""

    cliff_gap: float
    cliff_share: float


class CliffImpact(EconomyResultModel):
    """Exposure to tax-benefit cliffs under the baseline and under the reform."""

    baseline: CliffImpactInSimulation
    reform: CliffImpactInSimulation


class UKAreaImpact(EconomyResultModel):
    """The change in household net income in one published UK area.

    ``disclosure_tier`` is ``reported``, or ``approximate`` when the area's
    sample is thin; the ``_lower`` and ``_upper`` fields bound each change's
    90% interval. They are null for results stored before disclosure control.
    """

    average_household_income_change: float
    relative_household_income_change: float
    population: float
    disclosure_tier: Literal["reported", "approximate"] | None
    average_household_income_change_lower: float | None
    average_household_income_change_upper: float | None
    relative_household_income_change_lower: float | None
    relative_household_income_change_upper: float | None


class ConstituencyImpact(UKAreaImpact):
    """The reform's impact in one UK parliamentary constituency."""

    constituency_code: str
    constituency_name: str


class LocalAuthorityImpact(UKAreaImpact):
    """The reform's impact in one UK local authority."""

    local_authority_code: str
    local_authority_name: str


class CongressionalDistrictImpact(EconomyResultModel):
    """The reform's impact in one US congressional district.

    ``district`` is the state and two-digit number, such as ``"CA-12"``; an
    at-large district is ``01``. The percentages are the shares of people
    whose household net income rises, falls or stays the same.
    """

    district: str
    average_household_income_change: float
    relative_household_income_change: float
    winner_percentage: float
    loser_percentage: float
    no_change_percentage: float
    population: float


class CongressionalDistrictImpacts(EconomyResultModel):
    """The reform's impact in each congressional district of a US state report."""

    districts: list[CongressionalDistrictImpact]


def _is_none(value: object) -> bool:
    return value is None


class EconomyResult(EconomyResultModel):
    """A report run's single-year economy result, in the format the app reads.

    ``model_version`` is the country package version the run used, and
    ``data_version`` the data release. ``spm_provenance`` is the baseline's
    and reform's SPM calculation receipts the simulation service stored, as
    the Public API's ``SPMComparisonProvenance`` (serialized, as the Public
    API serializes it elsewhere, with package names as its runtime version
    keys), or null. ``wealth_decile`` and ``intra_wealth_decile`` are UK-only;
    ``poverty_by_race`` and ``congressional_district_impact`` US-only; the
    constituency and local-authority impacts are UK-only and null when the
    run did not compute them; a local-area report's run computes both, so a
    level whose every area was withheld is empty. ``constituency_withheld_codes``
    and ``local_authority_withheld_codes`` are a local-area report's sorted
    codes of the areas each level withheld, empty when it withheld none; for
    every other report they are null and left out of the JSON, as the
    simulation service leaves them out. ``labor_supply_response`` and
    ``cliff_impact`` are null when the run did not compute them.
    """

    spm_provenance: SPMComparisonProvenance | None
    model_version: str
    data_version: str
    budget: BudgetaryImpact
    detailed_budget: dict[str, ProgramBudget]
    decile: DecileChange
    inequality: InequalityChange
    poverty: PovertyByAge
    poverty_by_gender: PovertyByGender
    poverty_by_race: PovertyByRace | None
    intra_decile: IntraDecileShares
    wealth_decile: DecileChange | None
    intra_wealth_decile: IntraDecileShares | None
    labor_supply_response: LaborSupplyResponse | None
    constituency_impact: list[ConstituencyImpact] | None
    local_authority_impact: list[LocalAuthorityImpact] | None
    congressional_district_impact: CongressionalDistrictImpacts | None
    constituency_withheld_codes: list[str] | None = Field(
        default=None, exclude_if=_is_none
    )
    local_authority_withheld_codes: list[str] | None = Field(
        default=None, exclude_if=_is_none
    )
    cliff_impact: CliffImpact | None


@dataclass(frozen=True)
class ReportRunResultColumns:
    """The result columns of the report run itself.

    ``country_package_version`` is the run's; the four cliff columns are all
    set or all null.
    """

    country_package_version: str
    data_version: str | None
    spm_provenance: dict[str, JsonValue] | None
    baseline_cliff_gap: float | None
    baseline_cliff_share: float | None
    reform_cliff_gap: float | None
    reform_cliff_share: float | None


@dataclass(frozen=True)
class EconomyResultRows:
    """Every result row of one report run, as the database connectors read them.

    The comparison tables' rows are the report run's; the poverty and
    inequality rows are those of its baseline and reform simulation runs.
    ``on_local_area_dataset`` says whether the run is a local-area report's,
    whose ``withheld_area_codes`` rows are read and list every area its
    writer withheld; for any other run they are not read.
    """

    country_id: str
    report_run: ReportRunResultColumns
    baseline_simulation_run_id: UUID
    reform_simulation_run_id: UUID
    budget_summary: tuple[BudgetSummaryRow, ...]
    program_statistics: tuple[ProgramStatisticsRow, ...]
    decile_impacts: tuple[DecileImpactRow, ...]
    intra_decile_impacts: tuple[IntraDecileImpactRow, ...]
    poverty: tuple[PovertyRow, ...]
    inequality: tuple[InequalityRow, ...]
    labor_supply_responses: tuple[LaborSupplyResponseRow, ...]
    labor_supply_decile_responses: tuple[LaborSupplyDecileResponseRow, ...]
    congressional_district_impacts: tuple[CongressionalDistrictImpactRow, ...]
    constituency_impacts: tuple[ConstituencyImpactRow, ...]
    local_authority_impacts: tuple[LocalAuthorityImpactRow, ...]
    on_local_area_dataset: bool = False
    withheld_area_codes: tuple[WithheldAreaCodeRow, ...] = ()
