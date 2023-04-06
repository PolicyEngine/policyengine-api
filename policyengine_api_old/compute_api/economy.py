from policyengine_api.country import COUNTRIES
from policyengine_api.data import database
from policyengine_api.endpoints.policy import create_policy_reform
from policyengine_core.simulations import Microsimulation
from policyengine_core.experimental import MemoryConfig
import json


def compute_general_economy(simulation: Microsimulation) -> dict:
    total_tax = simulation.calculate("household_tax").sum()
    personal_hh_equiv_income = simulation.calculate(
        "equiv_household_net_income"
    )
    household_count_people = simulation.calculate("household_count_people")
    personal_hh_equiv_income.weights *= household_count_people
    gini = personal_hh_equiv_income.gini()
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
        wealth_decile = wealth.decile_rank().astype(int).tolist()
        wealth = wealth.astype(float).tolist()
    except:
        wealth = None
        wealth_decile = None
    try:
        is_male = simulation.calculate("is_male").astype(bool).tolist()
    except:
        is_male = None
    return {
        "total_net_income": simulation.calculate("household_net_income").sum(),
        "total_tax": total_tax,
        "total_benefits": simulation.calculate("household_benefits").sum(),
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
        "type": "general",
    }


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
):
    country = COUNTRIES.get(country_id)
    policy_json = database.get_in_table(
        "policy", country_id=country_id, id=policy_id
    )["policy_json"]
    policy_data = json.loads(policy_json)
    if country_id == "us":
        us_modelled_states = country.tax_benefit_system.modelled_policies[
            "filtered"
        ]["state_name"].keys()
        us_modelled_states = [state.lower() for state in us_modelled_states]
        if (region == "us") or (region.lower() not in us_modelled_states):
            policy_data["simulation.reported_state_income_tax"] = {
                "2010-01-01.2030-01-01": True
            }
    reform = create_policy_reform(country_id, policy_data)

    simulation: Microsimulation = country.country_package.Microsimulation(
        reform=reform,
    )
    simulation.memory_config = MemoryConfig(0.4)
    simulation.default_calculation_period = time_period

    original_household_weight = simulation.calculate("household_weight").values

    if country_id == "uk":
        if region != "uk":
            region_values = simulation.calculate("country").values
            region_decoded = dict(
                eng="ENGLAND",
                wales="WALES",
                scot="SCOTLAND",
                ni="NORTHERN_IRELAND",
            )[region]
            simulation.set_input(
                "household_weight",
                time_period,
                original_household_weight * (region_values == region_decoded),
            )
    elif country_id == "us":
        if region != "us":
            region_values = simulation.calculate("state_code_str").values
            simulation.set_input(
                "household_weight",
                time_period,
                original_household_weight * (region_values == region.upper()),
            )
    for time_period in simulation.get_holder(
        "person_weight"
    ).get_known_periods():
        simulation.delete_arrays("person_weight", time_period)

    if options.get("target") == "cliff":
        return compute_cliff_impact(simulation)

    return compute_general_economy(simulation)
