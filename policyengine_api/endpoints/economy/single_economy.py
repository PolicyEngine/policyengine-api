from policyengine_api.country import COUNTRIES, create_policy_reform
from policyengine_core.simulations import Microsimulation
from policyengine_core.experimental import MemoryConfig
import json

from policyengine_us import Microsimulation
from policyengine_uk import Microsimulation
import time
import os
import traceback


def compute_general_economy(
    simulation: Microsimulation,
    country_id: str = None,
) -> dict:

    total_tax = simulation.calculate("household_tax").sum()
    total_spending = simulation.calculate("household_benefits").sum()

    if country_id == "uk":
        total_tax = simulation.calculate("gov_tax").sum()
        total_spending = simulation.calculate("gov_spending").sum()
    personal_hh_equiv_income = simulation.calculate(
        "equiv_household_net_income"
    )
    personal_hh_equiv_income[personal_hh_equiv_income < 0] = 0
    household_count_people = simulation.calculate("household_count_people")
    personal_hh_equiv_income.weights *= household_count_people
    try:
        gini = personal_hh_equiv_income.gini()
    except:
        print(
            "WARNING: Gini index calculations resulted in an error: returning no change, but this is inaccurate."
        )
        gini = 0.4
    in_top_10_pct = personal_hh_equiv_income.decile_rank() == 10
    in_top_1_pct = personal_hh_equiv_income.percentile_rank() == 100
    personal_hh_equiv_income.weights /= household_count_people
    top_10_percent_share = (
        personal_hh_equiv_income[in_top_10_pct].sum()
        / personal_hh_equiv_income.sum()
    )
    top_1_percent_share = (
        personal_hh_equiv_income[in_top_1_pct].sum()
        / personal_hh_equiv_income.sum()
    )
    try:
        wealth = simulation.calculate("total_wealth")
        wealth.weights *= household_count_people
        wealth_decile = wealth.decile_rank().clip(1, 10).astype(int).tolist()
        wealth = wealth.astype(float).tolist()
    except:
        wealth = None
        wealth_decile = None
    try:
        is_male = simulation.calculate("is_male").astype(bool).tolist()
    except:
        is_male = None
    try:
        race = simulation.calculate("race").astype(str).tolist()
    except:
        race = None
    try:
        total_state_tax = simulation.calculate(
            "household_state_income_tax"
        ).sum()
    except Exception as e:
        total_state_tax = 0

    # Labour supply responses
    substitution_lsr = 0
    income_lsr = 0
    budgetary_impact_lsr = 0
    income_lsr_hh = (household_count_people * 0).astype(float).tolist()
    substitution_lsr_hh = (household_count_people * 0).astype(float).tolist()
    if (
        "employment_income_behavioral_response"
        in simulation.tax_benefit_system.variables
    ):
        if any(
            simulation.calculate("employment_income_behavioral_response") != 0
        ):
            substitution_lsr = simulation.calculate(
                "substitution_elasticity_lsr"
            ).sum()
            income_lsr = simulation.calculate("income_elasticity_lsr").sum()

            income_lsr_hh = (
                simulation.calculate(
                    "income_elasticity_lsr", map_to="household"
                )
                .astype(float)
                .tolist()
            )
            substitution_lsr_hh = (
                simulation.calculate(
                    "substitution_elasticity_lsr", map_to="household"
                )
                .astype(float)
                .tolist()
            )

    if country_id == "us":
        weekly_hours = simulation.calculate("weekly_hours_worked").sum()
        weekly_hours_income_effect = simulation.calculate(
            "weekly_hours_worked_behavioural_response_income_elasticity"
        ).sum()
        weekly_hours_substitution_effect = simulation.calculate(
            "weekly_hours_worked_behavioural_response_substitution_elasticity"
        ).sum()
    else:
        weekly_hours = 0
        weekly_hours_income_effect = 0
        weekly_hours_substitution_effect = 0

    result = {
        "total_net_income": simulation.calculate("household_net_income").sum(),
        "employment_income_hh": simulation.calculate(
            "employment_income",
            map_to="household",
        )
        .astype(float)
        .tolist(),
        "self_employment_income_hh": simulation.calculate(
            "self_employment_income",
            map_to="household",
        )
        .astype(float)
        .tolist(),
        "total_tax": total_tax,
        "total_state_tax": total_state_tax,
        "total_benefits": total_spending,
        "household_net_income": simulation.calculate("household_net_income")
        .astype(float)
        .tolist(),
        "equiv_household_net_income": simulation.calculate(
            "equiv_household_net_income",
        )
        .astype(float)
        .tolist(),
        "household_income_decile": simulation.calculate(
            "household_income_decile"
        )
        .astype(int)
        .tolist(),
        "household_market_income": simulation.calculate(
            "household_market_income"
        )
        .astype(float)
        .tolist(),
        "household_wealth_decile": wealth_decile,
        "household_wealth": wealth,
        "in_poverty": simulation.calculate("in_poverty").astype(bool).tolist(),
        "person_in_poverty": simulation.calculate(
            "in_poverty", map_to="person"
        )
        .astype(bool)
        .tolist(),
        "person_in_deep_poverty": simulation.calculate(
            "in_deep_poverty", map_to="person"
        )
        .astype(bool)
        .tolist(),
        "poverty_gap": simulation.calculate("poverty_gap").sum(),
        "deep_poverty_gap": simulation.calculate("deep_poverty_gap").sum(),
        "person_weight": simulation.calculate("person_weight")
        .astype(float)
        .tolist(),
        "age": simulation.calculate("age").astype(int).tolist(),
        "household_weight": simulation.calculate("household_weight")
        .astype(float)
        .tolist(),
        "household_count_people": simulation.calculate(
            "household_count_people"
        )
        .astype(int)
        .tolist(),
        "gini": float(gini),
        "top_10_percent_share": float(top_10_percent_share),
        "top_1_percent_share": float(top_1_percent_share),
        "is_male": is_male,
        "race": race,
        "substitution_lsr": float(substitution_lsr),
        "income_lsr": float(income_lsr),
        "budgetary_impact_lsr": float(budgetary_impact_lsr),
        "income_lsr_hh": income_lsr_hh,
        "substitution_lsr_hh": substitution_lsr_hh,
        "weekly_hours": weekly_hours,
        "weekly_hours_income_effect": weekly_hours_income_effect,
        "weekly_hours_substitution_effect": weekly_hours_substitution_effect,
        "type": "general",
        "programs": {},
    }
    if country_id == "uk":
        PROGRAMS = [
            "income_tax",
            "national_insurance",
            "vat",
            "council_tax",
            "fuel_duty",
            "tax_credits",
            "universal_credit",
            "child_benefit",
            "state_pension",
            "pension_credit",
            "ni_employer",
        ]
        IS_POSITIVE = [True] * 5 + [False] * 5 + [True]
        for program in PROGRAMS:
            result["programs"][program] = simulation.calculate(
                program, map_to="household"
            ).sum() * (1 if IS_POSITIVE[PROGRAMS.index(program)] else -1)
    return result


def compute_cliff_impact(
    simulation: Microsimulation,
):
    cliff_gap = simulation.calculate("cliff_gap")
    is_on_cliff = simulation.calculate("is_on_cliff")
    total_cliff_gap = cliff_gap.sum()
    total_adults = simulation.calculate("is_adult").sum()
    cliff_share = is_on_cliff.sum() / total_adults
    return {
        "cliff_gap": float(total_cliff_gap),
        "cliff_share": float(cliff_share),
        "type": "cliff",
    }


def compute_economy(
    country_id: str,
    policy_id: str,
    region: str,
    time_period: str,
    options: dict,
    policy_json: dict,
):
    start = time.time()
    country = COUNTRIES.get(country_id)
    policy_data = json.loads(policy_json)
    if country_id == "us":
        us_modelled_states = country.tax_benefit_system.modelled_policies[
            "filtered"
        ]["state_name"].keys()
        us_modelled_states = [state.lower() for state in us_modelled_states]
    reform = create_policy_reform(policy_data)
    Microsimulation: type = country.country_package.Microsimulation

    if country_id == "uk":
        simulation = Microsimulation(
            reform=reform,
        )
        simulation.default_calculation_period = time_period
        if region != "uk":
            region_values = simulation.calculate("country").values
            region_decoded = dict(
                eng="ENGLAND",
                wales="WALES",
                scot="SCOTLAND",
                ni="NORTHERN_IRELAND",
            )[region]
            df = simulation.to_input_dataframe()
            simulation = Microsimulation(
                dataset=df[region_values == region_decoded],
                reform=reform,
            )
    elif country_id == "us":
        if region != "us":
            from policyengine_us_data import (
                Pooled_3_Year_CPS_2023,
                EnhancedCPS_2024,
            )

            simulation = Microsimulation(
                dataset=Pooled_3_Year_CPS_2023,
                reform=reform,
            )
            df = simulation.to_input_dataframe()
            state_code = simulation.calculate(
                "state_code_str", map_to="person"
            ).values
            simulation.default_calculation_period = time_period
            if region == "nyc":
                in_nyc = simulation.calculate("in_nyc", map_to="person").values
                simulation = Microsimulation(dataset=df[in_nyc], reform=reform)
            elif region == "enhanced_us":
                simulation = Microsimulation(
                    dataset=EnhancedCPS_2024,
                    reform=reform,
                )
            else:
                simulation = Microsimulation(
                    dataset=df[state_code == region.upper()], reform=reform
                )
        else:
            simulation = Microsimulation(
                reform=reform,
            )

    simulation.subsample(
        int(
            options.get(
                "max_households", os.environ.get("MAX_HOUSEHOLDS", 1_000_000)
            )
        ),
        seed=(region, time_period),
        time_period=time_period,
    )
    simulation.default_calculation_period = time_period

    for time_period in simulation.get_holder(
        "person_weight"
    ).get_known_periods():
        simulation.delete_arrays("person_weight", time_period)

        if options.get("target") == "cliff":
            return compute_cliff_impact(simulation)
        print(f"Initialised simulation in {time.time() - start} seconds")
        start = time.time()
        economy = compute_general_economy(
            simulation,
            country_id=country_id,
        )
    print(f"Computed economy in {time.time() - start} seconds")
    return {"status": "ok", "result": economy}
