from policyengine_api.country import COUNTRIES, create_policy_reform
from policyengine_core.simulations import Microsimulation
from policyengine_core.experimental import MemoryConfig
import json

from policyengine_us import Microsimulation
from policyengine_uk import Microsimulation
import time
import os
from rq import get_current_job
from policyengine_api.utils.worker_logs import WorkerLogger
import numpy as np


def compute_general_economy(
    simulation: Microsimulation, country_id: str = None
) -> dict:
    # Initialize logging
    current_job = get_current_job()
    worker_id = current_job.worker_name
    logger = WorkerLogger(job_id=current_job.id)
    logger.log(f"Worker ID: {worker_id}")
    logger.memory_monitor.start()
    logger.log("Computing general economy")

    # Calculate tax and spending based on country
    total_tax = check_scalar_output(
        logger, simulation.calculate("household_tax").sum(), "total_tax"
    )
    total_spending = check_scalar_output(
        logger,
        simulation.calculate("household_benefits").sum(),
        "total_spending",
    )

    if country_id == "uk":
        total_tax = check_scalar_output(
            logger, simulation.calculate("gov_tax").sum(), "uk_total_tax"
        )
        total_spending = check_scalar_output(
            logger,
            simulation.calculate("gov_spending").sum(),
            "uk_total_spending",
        )

    # Calculate income and household metrics
    personal_hh_equiv_income = simulation.calculate(
        "equiv_household_net_income"
    )
    personal_hh_equiv_income[personal_hh_equiv_income < 0] = 0
    household_count_people = simulation.calculate("household_count_people")
    personal_hh_equiv_income.weights *= household_count_people

    # Calculate inequality metrics
    try:
        gini = check_scalar_output(
            logger, personal_hh_equiv_income.gini(), "gini"
        )
    except:
        logger.log(
            "WARNING: Gini index calculations resulted in an error: returning default value",
            level="warning",
        )
        gini = 0.4

    # Calculate percentile metrics
    in_top_10_pct = personal_hh_equiv_income.decile_rank() == 10
    in_top_1_pct = personal_hh_equiv_income.percentile_rank() == 100
    personal_hh_equiv_income.weights /= household_count_people

    # Calculate income shares
    top_10_percent_share = check_scalar_output(
        logger,
        personal_hh_equiv_income[in_top_10_pct].sum()
        / personal_hh_equiv_income.sum(),
        "top_10_percent_share",
    )
    top_1_percent_share = check_scalar_output(
        logger,
        personal_hh_equiv_income[in_top_1_pct].sum()
        / personal_hh_equiv_income.sum(),
        "top_1_percent_share",
    )

    # Calculate optional metrics with safe fallbacks
    def safe_calculate(calc_name, default=None, transform=None):
        try:
            value = simulation.calculate(calc_name)
            if transform:
                value = transform(value)
            return value
        except:
            logger.log(
                f"WARNING: {calc_name} calculation failed, using default value",
                level="warning",
            )
            return default

    # Wealth calculations
    try:
        wealth = simulation.calculate("total_wealth")
        wealth.weights *= household_count_people
        wealth_decile = wealth.decile_rank().clip(1, 10).astype(int).tolist()
        wealth = wealth.astype(float).tolist()
    except:
        logger.log("WARNING: Wealth calculations failed", level="warning")
        wealth = None
        wealth_decile = None

    # Demographic calculations
    is_male = safe_calculate(
        "is_male", transform=lambda x: x.astype(bool).tolist()
    )
    race = safe_calculate("race", transform=lambda x: x.astype(str).tolist())

    # Tax calculations
    total_state_tax = check_scalar_output(
        logger,
        safe_calculate(
            "household_state_income_tax",
            default=0,
            transform=lambda x: x.sum(),
        ),
        "total_state_tax",
    )

    # Labor supply response calculations
    lsr_values = {
        "substitution_lsr": 0,
        "income_lsr": 0,
        "budgetary_impact_lsr": 0,
        "income_lsr_hh": (household_count_people * 0).astype(float).tolist(),
        "substitution_lsr_hh": (household_count_people * 0)
        .astype(float)
        .tolist(),
    }

    if (
        "employment_income_behavioral_response"
        in simulation.tax_benefit_system.variables
    ):
        if any(
            simulation.calculate("employment_income_behavioral_response") != 0
        ):
            lsr_values.update(calculate_lsr_metrics(simulation, logger))

    # Country-specific calculations
    hours_metrics = calculate_hours_metrics(simulation, country_id, logger)

    # Construct result dictionary
    result = construct_result_dict(
        simulation,
        total_tax,
        total_state_tax,
        total_spending,
        gini,
        top_10_percent_share,
        top_1_percent_share,
        wealth,
        wealth_decile,
        is_male,
        race,
        lsr_values,
        hours_metrics,
    )

    # Add UK-specific program calculations
    if country_id == "uk":
        result["programs"] = calculate_uk_programs(simulation, logger)

    logger.memory_monitor.stop()
    logger.log("Finished computing general economy")
    return result


def calculate_lsr_metrics(simulation, logger):
    """Calculate labor supply response metrics"""
    substitution_lsr = check_scalar_output(
        logger,
        simulation.calculate("substitution_elasticity_lsr").sum(),
        "substitution_lsr",
    )
    income_lsr = check_scalar_output(
        logger,
        simulation.calculate("income_elasticity_lsr").sum(),
        "income_lsr",
    )

    lsr_branch = simulation.get_branch("lsr_measurement")
    lsr_revenue = (
        lsr_branch.calculate("household_net_income").sum()
        - lsr_branch.calculate("household_market_income").sum()
    )
    baseline_revenue = (
        simulation.calculate("household_net_income").sum()
        - simulation.calculate("household_market_income").sum()
    )
    budgetary_impact_lsr = check_scalar_output(
        logger, lsr_revenue - baseline_revenue, "budgetary_impact_lsr"
    )

    return {
        "substitution_lsr": float(substitution_lsr),
        "income_lsr": float(income_lsr),
        "budgetary_impact_lsr": float(budgetary_impact_lsr),
        "income_lsr_hh": simulation.calculate(
            "income_elasticity_lsr", map_to="household"
        )
        .astype(float)
        .tolist(),
        "substitution_lsr_hh": simulation.calculate(
            "substitution_elasticity_lsr", map_to="household"
        )
        .astype(float)
        .tolist(),
    }


def calculate_hours_metrics(simulation, country_id, logger):
    """Calculate hours-related metrics based on country"""
    if country_id != "us":
        return {
            "weekly_hours": 0,
            "weekly_hours_income_effect": 0,
            "weekly_hours_substitution_effect": 0,
        }

    return {
        "weekly_hours": check_scalar_output(
            logger,
            simulation.calculate("weekly_hours_worked").sum(),
            "weekly_hours",
        ),
        "weekly_hours_income_effect": check_scalar_output(
            logger,
            simulation.calculate(
                "weekly_hours_worked_behavioural_response_income_elasticity"
            ).sum(),
            "weekly_hours_income_effect",
        ),
        "weekly_hours_substitution_effect": check_scalar_output(
            logger,
            simulation.calculate(
                "weekly_hours_worked_behavioural_response_substitution_elasticity"
            ).sum(),
            "weekly_hours_substitution_effect",
        ),
    }


def calculate_uk_programs(simulation, logger):
    """Calculate UK-specific program values"""
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

    programs = {}
    for program in PROGRAMS:
        value = check_scalar_output(
            logger,
            simulation.calculate(program, map_to="household").sum()
            * (1 if IS_POSITIVE[PROGRAMS.index(program)] else -1),
            f"uk_program_{program}",
        )
        programs[program] = value

    return programs


def check_scalar_output(logger, value, calc_name: str):
    """
    Check if a scalar output contains NaN or None values and log a warning if found.

    Args:
        logger: WorkerLogger instance
        value: The value to check
        calc_name: Name of the calculation being checked
    """
    if value is None:
        logger.log(
            f"WARNING: {calc_name} calculation resulted in None value",
            level="warning",
        )
    elif np.isnan(value).any():
        logger.log(
            f"WARNING: {calc_name} calculation contains NaN values",
            level="warning",
        )
    return value


def safe_calculate_with_check(
    simulation, logger, variable_name: str, map_to: str = None, transform=None
):
    """
    Safely calculate a variable with NaN checking before and after transformation.

    Args:
        simulation: Microsimulation instance
        logger: WorkerLogger instance
        variable_name: Name of the variable to calculate
        map_to: Optional mapping target (e.g., 'household', 'person')
        transform: Optional transformation function to apply after calculation
    """
    # Calculate raw value
    calc_args = {"variable_name": variable_name}
    if map_to:
        calc_args["map_to"] = map_to

    raw_value = simulation.calculate(**calc_args)

    # Check raw value
    check_scalar_output(logger, raw_value, f"{variable_name}_raw")

    # Apply transformation if provided
    if transform:
        try:
            transformed_value = transform(raw_value)
            # Check transformed value
            return check_scalar_output(
                logger, transformed_value, f"{variable_name}_transformed"
            )
        except Exception as e:
            logger.log(
                f"WARNING: Transform failed for {variable_name}: {str(e)}",
                level="warning",
            )
            return raw_value

    return raw_value


def construct_result_dict(
    simulation,
    total_tax,
    total_state_tax,
    total_spending,
    gini,
    top_10_percent_share,
    top_1_percent_share,
    wealth,
    wealth_decile,
    is_male,
    race,
    lsr_values,
    hours_metrics,
):
    """Construct the final result dictionary"""
    logger = WorkerLogger(job_id=get_current_job().id)

    return {
        "total_net_income": safe_calculate_with_check(
            simulation,
            logger,
            "household_net_income",
            transform=lambda x: x.sum(),
        ),
        "employment_income_hh": safe_calculate_with_check(
            simulation,
            logger,
            "employment_income",
            map_to="household",
            transform=lambda x: x.astype(float).tolist(),
        ),
        "self_employment_income_hh": safe_calculate_with_check(
            simulation,
            logger,
            "self_employment_income",
            map_to="household",
            transform=lambda x: x.astype(float).tolist(),
        ),
        "total_tax": total_tax,
        "total_state_tax": total_state_tax,
        "total_benefits": total_spending,
        "household_net_income": safe_calculate_with_check(
            simulation,
            logger,
            "household_net_income",
            transform=lambda x: x.astype(float).tolist(),
        ),
        "equiv_household_net_income": safe_calculate_with_check(
            simulation,
            logger,
            "equiv_household_net_income",
            transform=lambda x: x.astype(float).tolist(),
        ),
        "household_income_decile": safe_calculate_with_check(
            simulation,
            logger,
            "household_income_decile",
            transform=lambda x: x.astype(int).tolist(),
        ),
        "household_market_income": safe_calculate_with_check(
            simulation,
            logger,
            "household_market_income",
            transform=lambda x: x.astype(float).tolist(),
        ),
        "household_wealth_decile": wealth_decile,
        "household_wealth": wealth,
        "in_poverty": safe_calculate_with_check(
            simulation,
            logger,
            "in_poverty",
            transform=lambda x: x.astype(bool).tolist(),
        ),
        "person_in_poverty": safe_calculate_with_check(
            simulation,
            logger,
            "in_poverty",
            map_to="person",
            transform=lambda x: x.astype(bool).tolist(),
        ),
        "person_in_deep_poverty": safe_calculate_with_check(
            simulation,
            logger,
            "in_deep_poverty",
            map_to="person",
            transform=lambda x: x.astype(bool).tolist(),
        ),
        "poverty_gap": safe_calculate_with_check(
            simulation, logger, "poverty_gap", transform=lambda x: x.sum()
        ),
        "deep_poverty_gap": safe_calculate_with_check(
            simulation, logger, "deep_poverty_gap", transform=lambda x: x.sum()
        ),
        "person_weight": safe_calculate_with_check(
            simulation,
            logger,
            "person_weight",
            transform=lambda x: x.astype(float).tolist(),
        ),
        "age": safe_calculate_with_check(
            simulation,
            logger,
            "age",
            transform=lambda x: x.astype(int).tolist(),
        ),
        "household_weight": safe_calculate_with_check(
            simulation,
            logger,
            "household_weight",
            transform=lambda x: x.astype(float).tolist(),
        ),
        "household_count_people": safe_calculate_with_check(
            simulation,
            logger,
            "household_count_people",
            transform=lambda x: x.astype(int).tolist(),
        ),
        "gini": float(gini),
        "top_10_percent_share": float(top_10_percent_share),
        "top_1_percent_share": float(top_1_percent_share),
        "is_male": is_male,
        "race": race,
        **lsr_values,
        **hours_metrics,
        "type": "general",
        "programs": {},
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
    policy_json: dict,
):
    start = time.time()
    current_job = get_current_job()
    logger = WorkerLogger(job_id=current_job.id)
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
    logger.log(f"Initialised simulation in {time.time() - start} seconds")
    economy = compute_general_economy(simulation, country_id=country_id)
    logger.log(f"Computed economy in {time.time() - start} seconds")
    return {"status": "ok", "result": economy}
