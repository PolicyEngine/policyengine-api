"""Economy results, and the result rows the simulation service stores them as.

``economy_result_rows`` follows the simulation service's writer,
``libs/policyengine-stage12-persistence/src/policyengine_stage12_persistence/
report_run_results.py`` in PolicyEngine/policyengine-sim-api (last changed in
``c02145fd``), field for field, so the Public API's rebuild of a result from
its rows is tested against the same mapping. Its ``withheld_area_codes`` rows
follow the writer as PolicyEngine/policyengine-sim-api#1068 changes it
(``46c38f07``): one row per code a result's ``constituency_withheld_codes``
and ``local_authority_withheld_codes`` list. Each row is a dict of the
table's columns; ``id`` and ``created_at`` are left for the caller.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

# .py's poverty types behind the result's "poverty" and "deep_poverty".
POVERTY_TYPES = {
    "us": {"poverty": "spm", "deep_poverty": "spm_deep"},
    "uk": {"poverty": "relative_bhc", "deep_poverty": "absolute_bhc"},
}
POVERTY_GROUPS = {
    "age": ("child", "adult", "senior"),
    "is_male": ("male", "female"),
    "race": ("white", "black", "hispanic", "other"),
}
INEQUALITY_INCOME_VARIABLES = {
    "us": "household_net_income",
    "uk": "equiv_hbai_household_net_income",
}
INTRA_DECILE_COLUMNS = {
    "Lose more than 5%": "lose_more_than_5pct",
    "Lose less than 5%": "lose_less_than_5pct",
    "No change": "no_change",
    "Gain less than 5%": "gain_less_than_5pct",
    "Gain more than 5%": "gain_more_than_5pct",
}
DISCLOSURE_FIELDS = (
    "disclosure_tier",
    "average_household_income_change_lower",
    "average_household_income_change_upper",
    "relative_household_income_change_lower",
    "relative_household_income_change_upper",
)
# The states the sample districts are in, and .py's at-large states.
STATE_FIPS = {"AK": 2, "CA": 6, "UT": 49}
AT_LARGE_STATES = frozenset({"AK"})


@dataclass(frozen=True)
class RunIds:
    """The report run, and the two simulation runs it compares."""

    report_run_id: UUID
    baseline_simulation_run_id: UUID
    reform_simulation_run_id: UUID


def _pair(baseline: float, reform: float) -> dict[str, float]:
    return {"baseline": baseline, "reform": reform}


def _age_poverty(start: float) -> dict[str, Any]:
    return {
        "child": _pair(start, start - 0.01),
        "adult": _pair(start + 0.02, start + 0.01),
        "senior": _pair(start + 0.03, start + 0.04),
        "all": _pair(start + 0.04, start + 0.02),
    }


def _intra_decile(offset: float) -> dict[str, Any]:
    deciles = {
        label: [
            round(offset + index * 0.01 + position * 0.001, 6) for index in range(10)
        ]
        for position, label in enumerate(INTRA_DECILE_COLUMNS)
    }
    return {
        "deciles": deciles,
        "all": {label: sum(values) / len(values) for label, values in deciles.items()},
    }


def _deciles(scale: float) -> dict[str, Any]:
    return {
        "average": {str(decile): scale * decile for decile in range(1, 11)},
        # Fractions a hundredfold change keeps exactly, as the rows hold
        # percentages.
        "relative": {str(decile): decile / 64 for decile in range(1, 11)},
    }


SPM_PROVENANCE = {
    "schema_version": "canonical-spm-comparison-v2",
    "baseline": {
        "receipt": {
            "schema_version": "canonical-spm-provenance-v2",
            "forecast_id": "spm-forecast-2026",
            "forecast_sha256": "a" * 64,
            "scenario": "baseline",
            "geography_kind": "county",
            "geography_id": None,
            "county_vintage": "2020",
            "as_of": None,
            "years": ["2026"],
            "runtime_versions": {
                "policyengine": "4.0.0",
                "policyengine-core": "3.0.0",
                "policyengine-us": "1.0.0",
                "spm-calculator": "0.5.0",
            },
        },
        "execution_count": 1,
    },
}
SPM_PROVENANCE["reform"] = copy.deepcopy(SPM_PROVENANCE["baseline"])


def us_economy_result() -> dict[str, Any]:
    """Return a US state report's economy result with every US-only part."""
    return {
        "spm_provenance": copy.deepcopy(SPM_PROVENANCE),
        "model_version": "1.0.0",
        "data_version": "enhanced_cps_2024@1.2.3",
        "budget": {
            "tax_revenue_impact": 1500.0,
            "state_tax_revenue_impact": 250.0,
            "benefit_spending_impact": -500.0,
            "budgetary_impact": 2000.0,
            "households": 130_000_000.0,
            "baseline_net_income": 9.5e12,
        },
        "detailed_budget": {
            "income_tax": {
                "baseline": 1000.0,
                "reform": 2500.0,
                "difference": 1500.0,
                "is_tax": True,
            },
            "snap": {
                "baseline": 800.0,
                "reform": 300.0,
                "difference": -500.0,
                "is_tax": False,
            },
            "state_income_tax": {
                "baseline": 10.0,
                "reform": 260.0,
                "difference": 250.0,
                "is_tax": None,
            },
        },
        "decile": _deciles(10.0),
        "inequality": {
            "gini": _pair(0.41, 0.4),
            "top_10_pct_share": _pair(0.32, 0.31),
            "top_1_pct_share": _pair(0.11, 0.105),
        },
        "poverty": {"poverty": _age_poverty(0.1), "deep_poverty": _age_poverty(0.04)},
        "poverty_by_gender": {
            "poverty": {"male": _pair(0.11, 0.1), "female": _pair(0.13, 0.12)},
            "deep_poverty": {"male": _pair(0.04, 0.035), "female": _pair(0.05, 0.045)},
        },
        "poverty_by_race": {
            "poverty": {
                "white": _pair(0.08, 0.07),
                "black": _pair(0.18, 0.16),
                "hispanic": _pair(0.16, 0.15),
                "other": _pair(0.12, 0.11),
            }
        },
        "intra_decile": _intra_decile(0.05),
        "wealth_decile": None,
        "intra_wealth_decile": None,
        "labor_supply_response": {
            "substitution_lsr": -120.0,
            "income_lsr": 45.0,
            "relative_lsr": {"income": 0.001, "substitution": -0.002},
            "total_change": -75.0,
            "revenue_change": -30.0,
            "decile": {
                "average": {
                    "income": {decile: 1.5 * decile for decile in range(1, 11)},
                    "substitution": {decile: -2.0 * decile for decile in range(1, 11)},
                },
                # .py reports relative responses only for deciles above zero.
                "relative": {
                    "income": {decile: 0.0001 * decile for decile in range(2, 11)},
                    "substitution": {
                        decile: -0.0002 * decile for decile in range(2, 11)
                    },
                },
            },
            "hours": {
                "baseline": 1.0e9,
                "reform": 0.999e9,
                "change": -1.0e6,
                "income_effect": 2.0e5,
                "substitution_effect": -1.2e6,
            },
        },
        "constituency_impact": None,
        "local_authority_impact": None,
        "congressional_district_impact": {
            "districts": [
                {
                    "district": "AK-01",
                    "average_household_income_change": 12.0,
                    "relative_household_income_change": 0.001,
                    "winner_percentage": 0.3,
                    "loser_percentage": 0.2,
                    "no_change_percentage": 0.5,
                    "population": 300_000.0,
                },
                {
                    "district": "CA-05",
                    "average_household_income_change": -4.0,
                    "relative_household_income_change": -0.0005,
                    "winner_percentage": 0.1,
                    "loser_percentage": 0.6,
                    "no_change_percentage": 0.3,
                    "population": 290_000.0,
                },
                {
                    "district": "CA-12",
                    "average_household_income_change": 7.5,
                    "relative_household_income_change": 0.0008,
                    "winner_percentage": 0.4,
                    "loser_percentage": 0.1,
                    "no_change_percentage": 0.5,
                    "population": 310_000.0,
                },
                {
                    "district": "UT-03",
                    "average_household_income_change": 3.0,
                    "relative_household_income_change": 0.0002,
                    "winner_percentage": 0.2,
                    "loser_percentage": 0.2,
                    "no_change_percentage": 0.6,
                    "population": 280_000.0,
                },
            ]
        },
        "cliff_impact": {
            "baseline": {"cliff_gap": 1.2e9, "cliff_share": 0.04},
            "reform": {"cliff_gap": 1.1e9, "cliff_share": 0.035},
        },
    }


def _area(code: str, name: str, kind: str, **values: Any) -> dict[str, Any]:
    return {
        f"{kind}_code": code,
        f"{kind}_name": name,
        "average_household_income_change": values.get("average", 10.0),
        "relative_household_income_change": values.get("relative", 0.001),
        "population": values.get("population", 40_000.0),
        "disclosure_tier": values.get("tier", "reported"),
        "average_household_income_change_lower": values.get("average_lower", 8.0),
        "average_household_income_change_upper": values.get("average_upper", 12.0),
        "relative_household_income_change_lower": values.get("relative_lower", 0.0008),
        "relative_household_income_change_upper": values.get("relative_upper", 0.0012),
    }


def uk_economy_result() -> dict[str, Any]:
    """Return a UK report's economy result with wealth deciles and area impacts.

    One constituency is approximate, and one local authority was stored
    before disclosure control, with no tier or intervals.
    """
    stored_before_disclosure = _area(
        "E06000002", "Middlesbrough", "local_authority", average=-3.0
    )
    for field in DISCLOSURE_FIELDS:
        stored_before_disclosure[field] = None
    return {
        "spm_provenance": None,
        "model_version": "2.0.0",
        "data_version": "enhanced_frs_2023_24@1.0.0",
        "budget": {
            "tax_revenue_impact": 4.0e9,
            "state_tax_revenue_impact": 0.0,
            "benefit_spending_impact": 1.0e9,
            "budgetary_impact": 3.0e9,
            "households": 28_000_000.0,
            "baseline_net_income": 1.2e12,
        },
        "detailed_budget": {
            "income_tax": {
                "baseline": 2.0e11,
                "reform": 2.04e11,
                "difference": 4.0e9,
                "is_tax": True,
            },
            "universal_credit": {
                "baseline": 6.0e10,
                "reform": 6.1e10,
                "difference": 1.0e9,
                "is_tax": False,
            },
        },
        "decile": _deciles(-5.0),
        "inequality": {
            "gini": _pair(0.36, 0.355),
            "top_10_pct_share": _pair(0.27, 0.265),
            "top_1_pct_share": _pair(0.08, 0.079),
        },
        "poverty": {"poverty": _age_poverty(0.17), "deep_poverty": _age_poverty(0.12)},
        "poverty_by_gender": {
            "poverty": {"male": _pair(0.16, 0.15), "female": _pair(0.18, 0.17)},
            "deep_poverty": {"male": _pair(0.11, 0.1), "female": _pair(0.13, 0.12)},
        },
        "poverty_by_race": None,
        "intra_decile": _intra_decile(0.02),
        "wealth_decile": _deciles(-8.0),
        "intra_wealth_decile": _intra_decile(0.03),
        "labor_supply_response": None,
        "constituency_impact": [
            _area("E14001063", "Aldershot", "constituency"),
            _area(
                "W07000081",
                "Aberafan Maesteg",
                "constituency",
                average=-2.5,
                tier="approximate",
            ),
        ],
        "local_authority_impact": [
            _area("E06000001", "Hartlepool", "local_authority", average=4.0),
            stored_before_disclosure,
        ],
        "congressional_district_impact": None,
        "cliff_impact": None,
    }


def uk_local_area_economy_result() -> dict[str, Any]:
    """Return a UK-wide report's result on the local-area dataset.

    It is a UK result with both area levels, and the sorted codes of the
    areas disclosure control withheld at each level.
    """
    return {
        **uk_economy_result(),
        "constituency_withheld_codes": ["S14000045"],
        "local_authority_withheld_codes": ["E06000064", "W06000015"],
    }


@dataclass(frozen=True)
class StoredEconomyResult:
    """What an economy result is stored as: report run columns and table rows."""

    report_run_columns: dict[str, Any]
    rows: dict[str, list[dict[str, Any]]]


def economy_result_rows(
    output: dict[str, Any], *, run_ids: RunIds, country: str
) -> StoredEconomyResult:
    """Return the rows the simulation service's writer stores ``output`` as."""
    report_keys = {
        "report_run_id": run_ids.report_run_id,
        "baseline_simulation_run_id": run_ids.baseline_simulation_run_id,
        "reform_simulation_run_id": run_ids.reform_simulation_run_id,
    }
    cliffs = output.get("cliff_impact")
    report_run_columns = {
        "baseline_cliff_gap": None
        if cliffs is None
        else cliffs["baseline"]["cliff_gap"],
        "baseline_cliff_share": (
            None if cliffs is None else cliffs["baseline"]["cliff_share"]
        ),
        "reform_cliff_gap": None if cliffs is None else cliffs["reform"]["cliff_gap"],
        "reform_cliff_share": None
        if cliffs is None
        else cliffs["reform"]["cliff_share"],
        "spm_provenance": output.get("spm_provenance"),
        "data_version": output["data_version"],
    }
    return StoredEconomyResult(
        report_run_columns=report_run_columns,
        rows={
            "labor_supply_responses": _labor_supply_rows(output, run_ids),
            "labor_supply_decile_responses": _labor_supply_decile_rows(output, run_ids),
            "budget_summary": _budget_rows(output, report_keys, country),
            "decile_impacts": _decile_rows(output, report_keys),
            "intra_decile_impacts": _intra_decile_rows(output, report_keys),
            "poverty": _poverty_rows(output, run_ids, country),
            "inequality": _inequality_rows(output, run_ids, country),
            "program_statistics": _program_rows(output, report_keys),
            "congressional_district_impacts": _district_rows(output, report_keys),
            "constituency_impacts": _area_rows(
                output.get("constituency_impact"), report_keys, "constituency"
            ),
            "local_authority_impacts": _area_rows(
                output.get("local_authority_impact"), report_keys, "local_authority"
            ),
            "withheld_area_codes": _withheld_rows(output, report_keys),
        },
    )


def _labor_supply_rows(output: dict[str, Any], run_ids: RunIds) -> list[dict[str, Any]]:
    response = output.get("labor_supply_response")
    if response is None:
        return []
    hours = response["hours"]
    return [
        {
            "report_run_id": run_ids.report_run_id,
            "income_effect_earnings_change": response["income_lsr"],
            "substitution_effect_earnings_change": response["substitution_lsr"],
            "total_earnings_change": response["total_change"],
            "revenue_change": response["revenue_change"],
            "relative_income_effect": response["relative_lsr"]["income"],
            "relative_substitution_effect": response["relative_lsr"]["substitution"],
            "baseline_weekly_hours": hours["baseline"],
            "reform_weekly_hours": hours["reform"],
            "weekly_hours_change": hours["change"],
            "weekly_hours_income_effect": hours["income_effect"],
            "weekly_hours_substitution_effect": hours["substitution_effect"],
        }
    ]


def _labor_supply_decile_rows(
    output: dict[str, Any], run_ids: RunIds
) -> list[dict[str, Any]]:
    response = output.get("labor_supply_response")
    if response is None:
        return []
    by_decile = response["decile"]
    values = {
        "average_income_effect": by_decile["average"]["income"],
        "average_substitution_effect": by_decile["average"]["substitution"],
        "relative_income_effect": by_decile["relative"]["income"],
        "relative_substitution_effect": by_decile["relative"]["substitution"],
    }
    deciles = sorted({int(decile) for column in values.values() for decile in column})
    return [
        {
            "report_run_id": run_ids.report_run_id,
            "decile": decile,
            **{
                column: column_values.get(decile)
                for column, column_values in values.items()
            },
        }
        for decile in deciles
    ]


def _budget_rows(
    output: dict[str, Any], keys: dict[str, Any], country: str
) -> list[dict[str, Any]]:
    figures = (
        ("tax_revenue_impact", "household_tax", "change"),
        ("benefit_spending_impact", "household_benefits", "change"),
        ("state_tax_revenue_impact", "household_state_income_tax", "change"),
        ("baseline_net_income", "household_net_income", "baseline_total"),
        ("households", "household_weight", "baseline_total"),
    )
    return [
        {
            **keys,
            "variable_name": variable,
            "entity": "household",
            column: output["budget"][figure],
        }
        for figure, variable, column in figures
        if variable != "household_state_income_tax" or country == "us"
    ]


def _decile_rows(output: dict[str, Any], keys: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _decile_type_rows(output["decile"], None, keys)
    if output.get("wealth_decile") is not None:
        rows += _decile_type_rows(
            output["wealth_decile"], "household_wealth_decile", keys
        )
    return rows


def _decile_type_rows(
    deciles: dict[str, Any], decile_variable: str | None, keys: dict[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            **keys,
            "income_variable": "household_net_income",
            "decile_variable": decile_variable,
            "entity": "household",
            "decile": int(decile),
            "quantiles": 10,
            "absolute_change": average,
            "relative_change": deciles["relative"][decile] * 100,
        }
        for decile, average in deciles["average"].items()
    ]


def _intra_decile_rows(
    output: dict[str, Any], keys: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = _intra_decile_type_rows(output["intra_decile"], "income", keys)
    if output.get("intra_wealth_decile") is not None:
        rows += _intra_decile_type_rows(output["intra_wealth_decile"], "wealth", keys)
    return rows


def _intra_decile_type_rows(
    shares: dict[str, Any], decile_type: str, keys: dict[str, Any]
) -> list[dict[str, Any]]:
    deciles = shares["deciles"]
    decile_count = max((len(values) for values in deciles.values()), default=0)
    return [
        {
            **keys,
            "decile_type": decile_type,
            "decile": index + 1,
            **{
                column: deciles[label][index]
                for label, column in INTRA_DECILE_COLUMNS.items()
                if index < len(deciles.get(label, ()))
            },
        }
        for index in range(decile_count)
    ]


def _poverty_rates(
    output: dict[str, Any],
) -> list[tuple[str, str | None, str | None, Any]]:
    rates: list[tuple[str, str | None, str | None, Any]] = []
    for measure in ("poverty", "deep_poverty"):
        by_age = output["poverty"][measure]
        rates.append((measure, None, None, by_age["all"]))
        rates += [
            (measure, "age", group, by_age[group]) for group in POVERTY_GROUPS["age"]
        ]
        by_gender = output["poverty_by_gender"][measure]
        rates += [
            (measure, "is_male", group, by_gender[group])
            for group in POVERTY_GROUPS["is_male"]
        ]
    if output.get("poverty_by_race") is not None:
        by_race = output["poverty_by_race"]["poverty"]
        rates += [
            ("poverty", "race", group, by_race[group])
            for group in POVERTY_GROUPS["race"]
        ]
    return rates


def _sides(run_ids: RunIds) -> tuple[tuple[str, UUID], ...]:
    return (
        ("baseline", run_ids.baseline_simulation_run_id),
        ("reform", run_ids.reform_simulation_run_id),
    )


def _poverty_rows(
    output: dict[str, Any], run_ids: RunIds, country: str
) -> list[dict[str, Any]]:
    poverty_types = POVERTY_TYPES[country]
    return [
        {
            "simulation_run_id": simulation_run_id,
            "poverty_type": poverty_types[measure],
            "entity": "person",
            "filter_variable": filter_variable,
            "filter_group": filter_group,
            "rate": rates[side],
        }
        for side, simulation_run_id in _sides(run_ids)
        for measure, filter_variable, filter_group, rates in _poverty_rates(output)
    ]


def _inequality_rows(
    output: dict[str, Any], run_ids: RunIds, country: str
) -> list[dict[str, Any]]:
    inequality = output["inequality"]
    return [
        {
            "simulation_run_id": simulation_run_id,
            "income_variable": INEQUALITY_INCOME_VARIABLES[country],
            "entity": "household",
            "gini": inequality["gini"][side],
            "top_10_share": inequality["top_10_pct_share"][side],
            "top_1_share": inequality["top_1_pct_share"][side],
        }
        for side, simulation_run_id in _sides(run_ids)
    ]


def _program_rows(output: dict[str, Any], keys: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            **keys,
            "program_name": program_name,
            "entity": None,
            "is_tax": program.get("is_tax"),
            "baseline_total": program["baseline"],
            "reform_total": program["reform"],
            "change": program["difference"],
        }
        for program_name, program in output["detailed_budget"].items()
    ]


def _district_rows(
    output: dict[str, Any], keys: dict[str, Any]
) -> list[dict[str, Any]]:
    impact = output.get("congressional_district_impact")
    if impact is None:
        return []
    rows = []
    for district in impact["districts"]:
        state, _, number = district["district"].partition("-")
        state_fips = STATE_FIPS[state]
        district_number = 0 if state in AT_LARGE_STATES else int(number)
        rows.append(
            {
                **keys,
                "district_geoid": state_fips * 100 + district_number,
                "state_fips": state_fips,
                "district_number": district_number,
                **{
                    field: district[field]
                    for field in (
                        "average_household_income_change",
                        "relative_household_income_change",
                        "winner_percentage",
                        "loser_percentage",
                        "no_change_percentage",
                        "population",
                    )
                },
            }
        )
    return rows


def _area_rows(
    areas: list[dict[str, Any]] | None, keys: dict[str, Any], kind: str
) -> list[dict[str, Any]]:
    if areas is None:
        return []
    return [
        {
            **keys,
            f"{kind}_code": area[f"{kind}_code"],
            f"{kind}_name": area[f"{kind}_name"],
            "average_household_income_change": area["average_household_income_change"],
            "relative_household_income_change": area[
                "relative_household_income_change"
            ],
            "population": area["population"],
            **{field: area.get(field) for field in DISCLOSURE_FIELDS},
        }
        for area in areas
    ]


def _withheld_rows(
    output: dict[str, Any], keys: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return a row per area code each level's withheld list names."""
    levels = (
        ("constituency", output.get("constituency_withheld_codes")),
        ("local_authority", output.get("local_authority_withheld_codes")),
    )
    return [
        {**keys, "area_type": area_type, "code": code}
        for area_type, codes in levels
        for code in codes or ()
    ]
