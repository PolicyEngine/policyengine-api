"""Reusable economy comparison calculations and response models."""

import logging
from collections.abc import Callable
from typing import NamedTuple

import h5py
import numpy as np
import pandas as pd
from microdf import MicroSeries
from policyengine_core.tools.hugging_face import download_huggingface_dataset
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Poverty is broken down into children (under 18), working-age adults and
# seniors (65 and over).
ADULT_MIN_AGE = 18
SENIOR_MIN_AGE = 65

# A relative income change above 5% (or below -5%) is large, and one within
# 0.1% of zero counts as no change.
LARGE_INCOME_CHANGE = 0.05
NO_INCOME_CHANGE_TOLERANCE = 1e-3

# Each bucket's label and the relative change an area must exceed to land in
# it, checked in order; an area that exceeds none loses more than 5%.
INCOME_CHANGE_BUCKET_THRESHOLDS = (
    ("Gain more than 5%", LARGE_INCOME_CHANGE),
    ("Gain less than 5%", NO_INCOME_CHANGE_TOLERANCE),
    ("No change", -NO_INCOME_CHANGE_TOLERANCE),
    ("Lose less than 5%", -LARGE_INCOME_CHANGE),
)
LARGEST_LOSS_BUCKET = "Lose more than 5%"
INCOME_CHANGE_BUCKETS = (
    *(label for label, _threshold in INCOME_CHANGE_BUCKET_THRESHOLDS),
    LARGEST_LOSS_BUCKET,
)

# Constituency and local-authority codes start with a letter for their nation.
UK_NATION_CODE_PREFIXES = {
    "england": "E",
    "scotland": "S",
    "wales": "W",
    "northern_ireland": "N",
}
UK_OUTCOME_REGIONS = ("uk", *UK_NATION_CODE_PREFIXES)

# These UK breakdown artifacts are postprocessor inputs, not the certified
# primary simulation dataset resolved through the PolicyEngine bundle.
UK_AREA_NAMES_REPO = "policyengine/policyengine-uk-data-public"


def budgetary_impact(baseline: dict, reform: dict) -> dict:
    """Return the reform's change in tax revenue, benefit spending and net budget.

    A positive ``budgetary_impact`` means the reform raises net revenue (tax
    revenue change minus benefit spending change).
    """
    tax_revenue_impact = reform["total_tax"] - baseline["total_tax"]
    state_tax_revenue_impact = reform["total_state_tax"] - baseline["total_state_tax"]
    benefit_spending_impact = reform["total_benefits"] - baseline["total_benefits"]
    budgetary_impact = tax_revenue_impact - benefit_spending_impact
    return {
        "budgetary_impact": budgetary_impact,
        "tax_revenue_impact": tax_revenue_impact,
        "state_tax_revenue_impact": state_tax_revenue_impact,
        "benefit_spending_impact": benefit_spending_impact,
        "households": sum(baseline["household_weight"]),
        "baseline_net_income": baseline["total_net_income"],
    }


def labor_supply_response(baseline: dict, reform: dict) -> dict:
    """Return the reform's labour supply responses relative to the baseline.

    This covers the income and substitution effects in total, as shares of
    original earnings, by income decile, and in weekly hours.
    """
    substitution_lsr = reform["substitution_lsr"] - baseline["substitution_lsr"]
    income_lsr = reform["income_lsr"] - baseline["income_lsr"]
    total_change = substitution_lsr + income_lsr
    revenue_change = reform["budgetary_impact_lsr"] - baseline["budgetary_impact_lsr"]

    substitution_lsr_hh = np.array(reform["substitution_lsr_hh"]) - np.array(
        baseline["substitution_lsr_hh"]
    )
    income_lsr_hh = np.array(reform["income_lsr_hh"]) - np.array(
        baseline["income_lsr_hh"]
    )
    decile = np.array(baseline["household_income_decile"])
    household_weight = baseline["household_weight"]

    total_lsr_hh = substitution_lsr_hh + income_lsr_hh

    emp_income = MicroSeries(baseline["employment_income_hh"], weights=household_weight)
    self_emp_income = MicroSeries(
        baseline["self_employment_income_hh"], weights=household_weight
    )
    earnings = emp_income + self_emp_income
    original_earnings = earnings - total_lsr_hh
    substitution_lsr_hh = MicroSeries(substitution_lsr_hh, weights=household_weight)
    income_lsr_hh = MicroSeries(income_lsr_hh, weights=household_weight)

    decile_avg = {
        "income": income_lsr_hh.groupby(decile).mean().to_dict(),
        "substitution": substitution_lsr_hh.groupby(decile).mean().to_dict(),
    }
    decile_rel = {
        "income": (
            income_lsr_hh.groupby(decile).sum()
            / original_earnings.groupby(decile).sum()
        ).to_dict(),
        "substitution": (
            substitution_lsr_hh.groupby(decile).sum()
            / original_earnings.groupby(decile).sum()
        ).to_dict(),
    }

    relative_lsr = {
        "income": (income_lsr_hh.sum() / original_earnings.sum()),
        "substitution": (substitution_lsr_hh.sum() / original_earnings.sum()),
    }

    decile_rel["income"] = {int(k): v for k, v in decile_rel["income"].items() if k > 0}
    decile_rel["substitution"] = {
        int(k): v for k, v in decile_rel["substitution"].items() if k > 0
    }

    hours = {
        "baseline": baseline["weekly_hours"],
        "reform": reform["weekly_hours"],
        "change": reform["weekly_hours"] - baseline["weekly_hours"],
        "income_effect": reform["weekly_hours_income_effect"]
        - baseline["weekly_hours_income_effect"],
        "substitution_effect": reform["weekly_hours_substitution_effect"]
        - baseline["weekly_hours_substitution_effect"],
    }

    return {
        "substitution_lsr": substitution_lsr,
        "income_lsr": income_lsr,
        "relative_lsr": relative_lsr,
        "total_change": total_change,
        "revenue_change": revenue_change,
        "decile": {
            "average": decile_avg,
            "relative": decile_rel,
        },
        "hours": hours,
    }


def detailed_budgetary_impact(
    baseline: dict, reform: dict, country_id: str | None
) -> dict:
    """Return baseline, reform and difference for each UK programme's budget.

    Only the UK reports programme-level totals; other countries get an empty dict.
    """
    result = {}
    if country_id == "uk":
        for program in baseline["programs"]:
            # baseline[programs][program] = total budgetary impact of program
            result[program] = {
                "baseline": baseline["programs"][program],
                "reform": reform["programs"][program],
                "difference": reform["programs"][program]
                - baseline["programs"][program],
            }
    return result


def decile_impact(baseline: dict, reform: dict) -> dict:
    """Compare the impact of a reform on the deciles of the population.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on the deciles of the population.

    """
    baseline_income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    reform_income = MicroSeries(
        reform["household_net_income"], weights=baseline_income.weights
    )

    # Filter out negative decile values
    decile = MicroSeries(baseline["household_income_decile"])
    baseline_income_filtered = baseline_income[decile >= 0]
    reform_income_filtered = reform_income[decile >= 0]

    income_change = reform_income_filtered - baseline_income_filtered
    rel_income_change_by_decile = (
        income_change.groupby(decile).sum()
        / baseline_income_filtered.groupby(decile).sum()
    )

    avg_income_change_by_decile = (
        income_change.groupby(decile).sum()
        / baseline_income_filtered.groupby(decile).count()
    )
    rel_decile_dict = rel_income_change_by_decile.to_dict()
    avg_decile_dict = avg_income_change_by_decile.to_dict()
    return {
        "relative": {int(k): v for k, v in rel_decile_dict.items()},
        "average": {int(k): v for k, v in avg_decile_dict.items()},
    }


def wealth_decile_impact(baseline: dict, reform: dict) -> dict:
    """Compare the impact of a reform on the deciles of the population.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on the deciles of the population.

    """
    baseline_income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    reform_income = MicroSeries(
        reform["household_net_income"], weights=baseline_income.weights
    )

    # Filter out negative decile values
    decile = MicroSeries(baseline["household_wealth_decile"])
    baseline_income_filtered = baseline_income[decile >= 0]
    reform_income_filtered = reform_income[decile >= 0]

    income_change = reform_income_filtered - baseline_income_filtered
    rel_income_change_by_decile = (
        income_change.groupby(decile).sum()
        / baseline_income_filtered.groupby(decile).sum()
    )
    avg_income_change_by_decile = (
        income_change.groupby(decile).sum()
        / baseline_income_filtered.groupby(decile).count()
    )
    rel_decile_dict = rel_income_change_by_decile.to_dict()
    avg_decile_dict = avg_income_change_by_decile.to_dict()
    return {
        "relative": {int(k): v for k, v in rel_decile_dict.items()},
        "average": {int(k): v for k, v in avg_decile_dict.items()},
    }


def inequality_impact(baseline: dict, reform: dict) -> dict:
    """Compare the impact of a reform on inequality.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on inequality.

    """
    return {
        "gini": {
            "baseline": baseline["gini"],
            "reform": reform["gini"],
        },
        "top_10_pct_share": {
            "baseline": baseline["top_10_percent_share"],
            "reform": reform["top_10_percent_share"],
        },
        "top_1_pct_share": {
            "baseline": baseline["top_1_percent_share"],
            "reform": reform["top_1_percent_share"],
        },
    }


def poverty_impact(baseline: dict, reform: dict) -> dict:
    """Compare the impact of a reform on poverty.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on poverty.

    """
    baseline_poverty = MicroSeries(
        baseline["person_in_poverty"], weights=baseline["person_weight"]
    )
    baseline_deep_poverty = MicroSeries(
        baseline["person_in_deep_poverty"], weights=baseline["person_weight"]
    )
    reform_poverty = MicroSeries(
        reform["person_in_poverty"], weights=baseline_poverty.weights
    )
    reform_deep_poverty = MicroSeries(
        reform["person_in_deep_poverty"], weights=baseline_poverty.weights
    )
    age = MicroSeries(baseline["age"])

    is_child = age < ADULT_MIN_AGE
    is_adult = (age >= ADULT_MIN_AGE) & (age < SENIOR_MIN_AGE)
    is_senior = age >= SENIOR_MIN_AGE

    poverty = {
        "child": {
            "baseline": float(baseline_poverty[is_child].mean()),
            "reform": float(reform_poverty[is_child].mean()),
        },
        "adult": {
            "baseline": float(baseline_poverty[is_adult].mean()),
            "reform": float(reform_poverty[is_adult].mean()),
        },
        "senior": {
            "baseline": float(baseline_poverty[is_senior].mean()),
            "reform": float(reform_poverty[is_senior].mean()),
        },
        "all": {
            "baseline": float(baseline_poverty.mean()),
            "reform": float(reform_poverty.mean()),
        },
    }

    deep_poverty = {
        "child": {
            "baseline": float(baseline_deep_poverty[is_child].mean()),
            "reform": float(reform_deep_poverty[is_child].mean()),
        },
        "adult": {
            "baseline": float(baseline_deep_poverty[is_adult].mean()),
            "reform": float(reform_deep_poverty[is_adult].mean()),
        },
        "senior": {
            "baseline": float(baseline_deep_poverty[is_senior].mean()),
            "reform": float(reform_deep_poverty[is_senior].mean()),
        },
        "all": {
            "baseline": float(baseline_deep_poverty.mean()),
            "reform": float(reform_deep_poverty.mean()),
        },
    }

    return {
        "poverty": poverty,
        "deep_poverty": deep_poverty,
    }


def compute_income_change(
    baseline_values: np.ndarray, reform_values: np.ndarray
) -> np.ndarray:
    """Return each household's income change as a fraction of baseline income.

    The baseline is floored at 1 so zero or negative incomes do not divide by zero.
    """
    absolute_change = reform_values - baseline_values
    capped_baseline = np.maximum(baseline_values, 1)
    return absolute_change / capped_baseline


def intra_decile_impact(baseline: dict, reform: dict) -> dict:
    """Return the share of people in each income decile by size of income change.

    People fall into five buckets (gain or lose more or less than 5%, or no change
    within 0.1%). ``all`` is the unweighted mean of the ten decile shares.
    """
    baseline_income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    reform_income = MicroSeries(
        reform["household_net_income"], weights=baseline_income.weights
    )
    people = MicroSeries(
        baseline["household_count_people"], weights=baseline_income.weights
    )
    decile = MicroSeries(baseline["household_income_decile"]).values  # noqa: PD011  # MicroSeries overrides .values, and .to_numpy() emits a different warning
    income_change = compute_income_change(baseline_income.values, reform_income.values)

    # Within each decile, calculate the percentage of people who:
    # 1. Gained more than 5% of their income
    # 2. Gained between 0% and 5% of their income
    # 3. Had no change in income
    # 3. Lost between 0% and 5% of their income
    # 4. Lost more than 5% of their income

    outcome_groups = {}
    all_outcomes = {}
    income_change_bounds = [-np.inf, -0.05, -1e-3, 1e-3, 0.05, np.inf]
    outcome_labels = [
        "Lose more than 5%",
        "Lose less than 5%",
        "No change",
        "Gain less than 5%",
        "Gain more than 5%",
    ]
    for lower, upper, label in zip(
        income_change_bounds[:-1], income_change_bounds[1:], outcome_labels, strict=True
    ):
        outcome_groups[label] = []
        for i in range(1, 11):
            in_decile: np.ndarray = decile == i
            in_group: np.ndarray = (income_change > lower) & (income_change <= upper)
            in_both: np.ndarray = in_decile & in_group

            people_in_both: np.float64 = people[in_both].sum()
            people_in_decile: np.float64 = people[in_decile].sum()

            # np.float64 does not raise ZeroDivisionError, instead returns NaN
            if people_in_decile == 0 and people_in_both == 0:
                people_in_proportion: float = 0.0
            else:
                people_in_proportion: float = float(people_in_both / people_in_decile)

            outcome_groups[label].append(people_in_proportion)

        all_outcomes[label] = sum(outcome_groups[label]) / 10
    return {"deciles": outcome_groups, "all": all_outcomes}


def intra_wealth_decile_impact(baseline: dict, reform: dict) -> dict:
    """Return the share of people in each wealth decile by size of income change.

    This uses the same buckets as ``intra_decile_impact``, grouped by household
    wealth decile instead of income decile.
    """
    baseline_income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    reform_income = MicroSeries(
        reform["household_net_income"], weights=baseline_income.weights
    )
    people = MicroSeries(
        baseline["household_count_people"], weights=baseline_income.weights
    )
    decile = MicroSeries(baseline["household_wealth_decile"]).values  # noqa: PD011  # MicroSeries overrides .values, and .to_numpy() emits a different warning
    income_change = compute_income_change(baseline_income.values, reform_income.values)

    # Within each decile, calculate the percentage of people who:
    # 1. Gained more than 5% of their income
    # 2. Gained between 0% and 5% of their income
    # 3. Had no change in income
    # 3. Lost between 0% and 5% of their income
    # 4. Lost more than 5% of their income

    outcome_groups = {}
    all_outcomes = {}
    income_change_bounds = [-np.inf, -0.05, -1e-3, 1e-3, 0.05, np.inf]
    outcome_labels = [
        "Lose more than 5%",
        "Lose less than 5%",
        "No change",
        "Gain less than 5%",
        "Gain more than 5%",
    ]
    for lower, upper, label in zip(
        income_change_bounds[:-1], income_change_bounds[1:], outcome_labels, strict=True
    ):
        outcome_groups[label] = []
        for i in range(1, 11):
            in_decile: np.ndarray = decile == i
            in_group: np.ndarray = (income_change > lower) & (income_change <= upper)
            in_both: np.ndarray = in_decile & in_group

            people_in_both: np.float64 = people[in_both].sum()
            people_in_decile: np.float64 = people[in_decile].sum()

            # np.float64 does not raise ZeroDivisionError, instead returns NaN
            if people_in_decile == 0 and people_in_both == 0:
                people_in_proportion = 0
            else:
                people_in_proportion: float = float(people_in_both / people_in_decile)

            outcome_groups[label].append(people_in_proportion)

        all_outcomes[label] = sum(outcome_groups[label]) / 10
    return {"deciles": outcome_groups, "all": all_outcomes}


def poverty_gender_breakdown(baseline: dict, reform: dict) -> dict:
    """Compare the impact of a reform on poverty.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on poverty.

    """
    if baseline["is_male"] is None:
        return {}
    baseline_poverty = MicroSeries(
        baseline["person_in_poverty"], weights=baseline["person_weight"]
    )
    baseline_deep_poverty = MicroSeries(
        baseline["person_in_deep_poverty"], weights=baseline["person_weight"]
    )
    reform_poverty = MicroSeries(
        reform["person_in_poverty"], weights=baseline_poverty.weights
    )
    reform_deep_poverty = MicroSeries(
        reform["person_in_deep_poverty"], weights=baseline_poverty.weights
    )
    is_male = MicroSeries(baseline["is_male"])

    poverty = {
        "male": {
            "baseline": float(baseline_poverty[is_male].mean()),
            "reform": float(reform_poverty[is_male].mean()),
        },
        "female": {
            "baseline": float(baseline_poverty[~is_male].mean()),
            "reform": float(reform_poverty[~is_male].mean()),
        },
    }

    deep_poverty = {
        "male": {
            "baseline": float(baseline_deep_poverty[is_male].mean()),
            "reform": float(reform_deep_poverty[is_male].mean()),
        },
        "female": {
            "baseline": float(baseline_deep_poverty[~is_male].mean()),
            "reform": float(reform_deep_poverty[~is_male].mean()),
        },
    }

    return {
        "poverty": poverty,
        "deep_poverty": deep_poverty,
    }


def poverty_racial_breakdown(baseline: dict, reform: dict) -> dict:
    """Compare the impact of a reform on poverty.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.

    Returns:
        dict: The impact of the reform on poverty.

    """
    if baseline["race"] is None:
        return {}
    baseline_poverty = MicroSeries(
        baseline["person_in_poverty"], weights=baseline["person_weight"]
    )
    reform_poverty = MicroSeries(
        reform["person_in_poverty"], weights=baseline_poverty.weights
    )
    race = MicroSeries(baseline["race"])  # Can be WHITE, BLACK, HISPANIC, or OTHER.

    poverty = {
        "white": {
            "baseline": float(baseline_poverty[race == "WHITE"].mean()),
            "reform": float(reform_poverty[race == "WHITE"].mean()),
        },
        "black": {
            "baseline": float(baseline_poverty[race == "BLACK"].mean()),
            "reform": float(reform_poverty[race == "BLACK"].mean()),
        },
        "hispanic": {
            "baseline": float(baseline_poverty[race == "HISPANIC"].mean()),
            "reform": float(reform_poverty[race == "HISPANIC"].mean()),
        },
        "other": {
            "baseline": float(baseline_poverty[race == "OTHER"].mean()),
            "reform": float(reform_poverty[race == "OTHER"].mean()),
        },
    }

    return {
        "poverty": poverty,
    }


class UKConstituencyBreakdownByConstituency(BaseModel):
    """One constituency's household income change and its map position (x, y)."""

    average_household_income_change: float
    relative_household_income_change: float
    x: int
    y: int


class UKConstituencyBreakdown(BaseModel):
    """UK reform results by constituency.

    ``outcomes_by_region`` counts how many constituencies in the UK and each nation
    fall into each income-change bucket.
    """

    by_constituency: dict[str, UKConstituencyBreakdownByConstituency]
    outcomes_by_region: dict[str, dict[str, int]]


class UKLocalAuthorityBreakdownByLA(BaseModel):
    """One local authority's household income change and its map position (x, y)."""

    average_household_income_change: float
    relative_household_income_change: float
    x: int
    y: int


class UKLocalAuthorityBreakdown(BaseModel):
    """UK reform results by local authority.

    ``outcomes_by_region`` counts how many local authorities in the UK and each
    nation fall into each income-change bucket.
    """

    by_local_authority: dict[str, UKLocalAuthorityBreakdownByLA]
    outcomes_by_region: dict[str, dict[str, int]]


class _UKAreaData(NamedTuple):
    """One UK area family's household weights and its area table.

    ``weights[i, j]`` is the weight of household record ``j`` in the area on row
    ``i`` of ``names``, whose columns are code, name and map position (x, y).
    """

    weights: np.ndarray
    names: pd.DataFrame


class _UKAreaFilter(NamedTuple):
    """The single area, or the nation's code prefix, a region limits output to."""

    selected_area: str | None
    nation_code_prefix: str | None

    def includes(self, name: str, code: str) -> bool:
        """Return whether the area with this name and code passes the filter."""
        if self.selected_area is not None and self.selected_area not in (
            name,
            code,
        ):
            return False
        # Match the leading nation letter with startswith, so a letter anywhere
        # else in the code cannot place the area in the wrong nation.
        return self.nation_code_prefix is None or code.startswith(
            self.nation_code_prefix
        )


def _uk_area_filter(
    region: str | None,
    *,
    area_region_prefix: str,
    normalize_nation: Callable[[str], str],
) -> _UKAreaFilter:
    """Read the area or nation a region selects.

    ``normalize_nation`` gives the case in which the region's nation name is
    compared with the known nations.
    """
    selected_area = None
    if region is not None and region.startswith(area_region_prefix):
        selected_area = region.split("/", 1)[1]

    nation_code_prefix = None
    if region is not None and region.startswith("country/"):
        selected_nation = normalize_nation(region.split("/", 1)[1])
        nation_code_prefix = {
            normalize_nation(nation): prefix
            for nation, prefix in UK_NATION_CODE_PREFIXES.items()
        }.get(selected_nation)
    return _UKAreaFilter(selected_area, nation_code_prefix)


def _load_uk_area_data(
    *, weights_repo: str, weights_filename: str, names_filename: str
) -> _UKAreaData:
    """Download one area family's 2025 household weights and its area table."""
    weights_path = download_huggingface_dataset(
        repo=weights_repo,
        repo_filename=weights_filename,
    )
    with h5py.File(weights_path, "r") as weights_file:
        weights = weights_file["2025"][...]

    names_path = download_huggingface_dataset(
        repo=UK_AREA_NAMES_REPO,
        repo_filename=names_filename,
    )
    return _UKAreaData(weights=weights, names=pd.read_csv(names_path))


def _income_change_bucket(relative_change: float) -> str:
    """Return the income-change bucket a relative household income change is in."""
    for label, threshold in INCOME_CHANGE_BUCKET_THRESHOLDS:
        if relative_change > threshold:
            return label
    return LARGEST_LOSS_BUCKET


def _outcome_regions(code: str) -> list[str]:
    """Return the UK and, when its code names one, the nation an area counts in."""
    regions = ["uk"]
    for nation, prefix in UK_NATION_CODE_PREFIXES.items():
        if code.startswith(prefix):
            regions.append(nation)
            break
    return regions


def _uk_area_breakdown(
    baseline_net_income: object,
    reform_net_income: object,
    area_data: _UKAreaData,
    area_filter: _UKAreaFilter,
) -> tuple[dict[str, dict], dict[str, dict[str, int]]]:
    """Return each selected area's income change and the bucket counts by region.

    The first mapping is keyed by area name in table order; the second counts
    the selected areas in the UK and each nation by income-change bucket.
    """
    by_area: dict[str, dict] = {}
    outcomes_by_region = {
        region_name: dict.fromkeys(INCOME_CHANGE_BUCKETS, 0)
        for region_name in UK_OUTCOME_REGIONS
    }
    for index in range(len(area_data.names)):
        name: str = area_data.names.iloc[index]["name"]
        code: str = area_data.names.iloc[index]["code"]
        if not area_filter.includes(name, code):
            continue

        weight: np.ndarray = area_data.weights[index]
        baseline_income = MicroSeries(baseline_net_income, weights=weight)
        reform_income = MicroSeries(reform_net_income, weights=weight)
        average_household_income_change: float = (
            reform_income.sum() - baseline_income.sum()
        ) / baseline_income.count()
        percent_household_income_change: float = (
            reform_income.sum() / baseline_income.sum() - 1
        )
        by_area[name] = {
            "average_household_income_change": average_household_income_change,
            "relative_household_income_change": percent_household_income_change,
            "x": int(area_data.names.iloc[index]["x"]),  # Geographic positions
            "y": int(area_data.names.iloc[index]["y"]),
        }

        bucket = _income_change_bucket(percent_household_income_change)
        for region_name in _outcome_regions(code):
            outcomes_by_region[region_name][bucket] += 1
    return by_area, outcomes_by_region


def uk_constituency_breakdown(
    baseline: dict, reform: dict, country_id: str | None, region: str | None = None
) -> UKConstituencyBreakdown | None:
    """Return each UK constituency's average and relative household income change.

    Return None outside the UK or for a local-authority region. A constituency or
    country region limits the output to that area. Constituency weights and
    names come from PolicyEngine's Hugging Face datasets.
    """
    if country_id != "uk":
        return None

    # If simulating a local authority, constituency breakdown is not applicable
    if region is not None and region.startswith("local_authority/"):
        return None

    area_filter = _uk_area_filter(
        region,
        area_region_prefix="constituency/",
        normalize_nation=str.upper,
    )
    baseline_net_income = baseline["household_net_income"]
    reform_net_income = reform["household_net_income"]
    constituencies = _load_uk_area_data(
        weights_repo="policyengine/policyengine-uk-data",
        weights_filename="parliamentary_constituency_weights.h5",
        names_filename="constituencies_2024.csv",
    )
    by_constituency, outcomes_by_region = _uk_area_breakdown(
        baseline_net_income, reform_net_income, constituencies, area_filter
    )
    return UKConstituencyBreakdown(
        by_constituency=by_constituency,
        outcomes_by_region=outcomes_by_region,
    )


def uk_local_authority_breakdown(
    baseline: dict, reform: dict, country_id: str | None, region: str | None = None
) -> UKLocalAuthorityBreakdown | None:
    """Return each UK local authority's average and relative household income change.

    Return None outside the UK or for a constituency region. A local-authority or
    country region limits the output to that area. Local-authority weights and
    names come from PolicyEngine's Hugging Face datasets.
    """
    if country_id != "uk":
        return None

    # If simulating a constituency, local authority breakdown is not applicable
    if region is not None and region.startswith("constituency/"):
        return None

    area_filter = _uk_area_filter(
        region,
        area_region_prefix="local_authority/",
        normalize_nation=str.lower,
    )
    baseline_net_income = baseline["household_net_income"]
    reform_net_income = reform["household_net_income"]
    local_authorities = _load_uk_area_data(
        weights_repo="policyengine/policyengine-uk-data-private",
        weights_filename="local_authority_weights.h5",
        names_filename="local_authorities_2021.csv",
    )
    by_local_authority, outcomes_by_region = _uk_area_breakdown(
        baseline_net_income, reform_net_income, local_authorities, area_filter
    )
    return UKLocalAuthorityBreakdown(
        by_local_authority=by_local_authority,
        outcomes_by_region=outcomes_by_region,
    )


def compare_economic_outputs(
    baseline: dict,
    reform: dict,
    country_id: str | None = None,
    region: str | None = None,
) -> dict:
    """Compare the economic outputs of two economies.

    Args:
        baseline (dict): The baseline economy.
        reform (dict): The reform economy.
        country_id (str): The country identifier (e.g., "uk", "us").
        region (str | None): The region filter (e.g., "uk", "local_authority/Leicester",
            "constituency/Aldershot", "country/scotland"). Used to filter breakdown
            results.

    Returns:
        dict: The comparison of the two economies.

    """
    if baseline.get("type") == "general":
        budgetary_impact_data = budgetary_impact(baseline, reform)
        detailed_budgetary_impact_data = detailed_budgetary_impact(
            baseline, reform, country_id
        )
        decile_impact_data = decile_impact(baseline, reform)
        inequality_impact_data = inequality_impact(baseline, reform)
        poverty_impact_data = poverty_impact(baseline, reform)
        poverty_by_gender_data = poverty_gender_breakdown(baseline, reform)
        poverty_by_race_data = poverty_racial_breakdown(baseline, reform)
        intra_decile_impact_data = intra_decile_impact(baseline, reform)
        labor_supply_response_data = labor_supply_response(baseline, reform)
        constituency_impact_data: UKConstituencyBreakdown | None = (
            uk_constituency_breakdown(baseline, reform, country_id, region)
        )
        if constituency_impact_data is not None:
            constituency_impact_data = constituency_impact_data.model_dump()
        local_authority_impact_data: UKLocalAuthorityBreakdown | None = (
            uk_local_authority_breakdown(baseline, reform, country_id, region)
        )
        if local_authority_impact_data is not None:
            local_authority_impact_data = local_authority_impact_data.model_dump()
        try:
            wealth_decile_impact_data = wealth_decile_impact(baseline, reform)
            intra_wealth_decile_impact_data = intra_wealth_decile_impact(
                baseline, reform
            )
        except Exception:
            logger.exception(
                "Wealth decile impact computation failed; returning empty breakdowns."
            )
            wealth_decile_impact_data = {}
            intra_wealth_decile_impact_data = {}

        return {
            "budget": budgetary_impact_data,
            "detailed_budget": detailed_budgetary_impact_data,
            "decile": decile_impact_data,
            "inequality": inequality_impact_data,
            "poverty": poverty_impact_data,
            "poverty_by_gender": poverty_by_gender_data,
            "poverty_by_race": poverty_by_race_data,
            "intra_decile": intra_decile_impact_data,
            "wealth_decile": wealth_decile_impact_data,
            "intra_wealth_decile": intra_wealth_decile_impact_data,
            "labor_supply_response": labor_supply_response_data,
            "constituency_impact": constituency_impact_data,
            "local_authority_impact": local_authority_impact_data,
        }
    if baseline.get("type") == "cliff":
        return {
            "baseline": {
                "cliff_gap": baseline["cliff_gap"],
                "cliff_share": baseline["cliff_share"],
            },
            "reform": {
                "cliff_gap": reform["cliff_gap"],
                "cliff_share": reform["cliff_share"],
            },
        }
    return None
