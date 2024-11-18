from policyengine_core.simulations import Microsimulation
from typing import Dict

from policyengine_us import Microsimulation
from policyengine_uk import Microsimulation
from dataclasses import dataclass

@dataclass
class UKProgram:
    name: str
    is_positive: bool

class UKPrograms:
    PROGRAMS = [
        UKProgram("income_tax", True),
        UKProgram("national_insurance", True),
        UKProgram("vat", True),
        UKProgram("council_tax", True),
        UKProgram("fuel_duty", True),
        UKProgram("tax_credits", False),
        UKProgram("universal_credit", False),
        UKProgram("child_benefit", False),
        UKProgram("state_pension", False),
        UKProgram("pension_credit", False),
        UKProgram("ni_employer", True),
    ]


class GeneralEconomyTask:
    def __init__(self, simulation: Microsimulation, country_id: str):
        self.simulation = simulation
        self.country_id = country_id
        self.household_count_people = self.simulation.calculate("household_count_people")

    def calculate_tax_and_spending(self):
        if self.country_id == "uk":
            total_tax = self.simulation.calculate("gov_tax").sum()
            total_spending = self.simulation.calculate("gov_spending").sum()
        else:
            total_tax = self.simulation.calculate("household_tax").sum()
            total_spending = self.simulation.calculate("household_benefits").sum()
        return total_tax, total_spending
    
    def calculate_inequality_metrics(self):
        personal_hh_equiv_income = self._get_weighted_household_income()

        try:
            gini = personal_hh_equiv_income.gini()
        except Exception as e:
            print(
                "WARNING: Gini index calculations resulted in an error: returning no change, but this is inaccurate."
            )
            print("Error: ", e)
            gini = 0.4

        in_top_10_pct = personal_hh_equiv_income.decile_rank() == 10
        in_top_1_pct = personal_hh_equiv_income.percentile_rank() == 100
        
        personal_hh_equiv_income.weights /= self.household_count_people
        
        top_10_share = personal_hh_equiv_income[in_top_10_pct].sum() / personal_hh_equiv_income.sum()
        top_1_share = personal_hh_equiv_income[in_top_1_pct].sum() / personal_hh_equiv_income.sum()
        
        return gini, top_10_share, top_1_share

    def _get_weighted_household_income(self):
        income = self.simulation.calculate("equiv_household_net_income")
        income[income < 0] = 0
        income.weights *= self.household_count_people
        return income
    
    def calculate_income_breakdown_metrics(self):
        total_net_income = self.simulation.calculate("household_net_income").sum()
        employment_income_hh = self.simulation.calculate("employment_income", map_to="household").astype(float).tolist()
        self_employment_income_hh = self.simulation.calculate("self_employment_income", map_to="household").astype(float).tolist()

        return total_net_income, employment_income_hh, self_employment_income_hh
    
    def calculate_household_income_metrics(self):
        household_net_income = self.simulation.calculate("household_net_income").astype(float).tolist()
        equiv_household_net_income = self.simulation.calculate("equiv_household_net_income").astype(float).tolist()
        household_income_decile = self.simulation.calculate("household_income_decile").astype(int).tolist()
        household_market_income = self.simulation.calculate("household_market_income").astype(float).tolist()

        return household_net_income, equiv_household_net_income, household_income_decile, household_market_income

    
    def calculate_wealth_metrics(self):
        try:
            wealth = self.simulation.calculate("total_wealth")
            wealth.weights *= self.household_count_people
            wealth_decile = wealth.decile_rank().clip(1, 10).astype(int).tolist()
            wealth = wealth.astype(float).tolist()
        except Exception as e:
            wealth = None
            wealth_decile = None
        return wealth, wealth_decile
    
    def calculate_demographic_metrics(self):
        try:
            is_male = self.simulation.calculate("is_male").astype(bool).tolist()
        except Exception:
            is_male = None

        try:
            race = self.simulation.calculate("race").astype(str).tolist()
        except Exception:
            race = None

        age = self.simulation.calculate("age").astype(int).tolist()
            
        return is_male, race, age
    
    def calculate_poverty_metrics(self):
        in_poverty = self.simulation.calculate("in_poverty").astype(bool).tolist()
        person_in_poverty = self.simulation.calculate("in_poverty", map_to="person").astype(bool).tolist()
        person_in_deep_poverty = self.simulation.calculate("in_deep_poverty", map_to="person").astype(bool).tolist()
        poverty_gap = self.simulation.calculate("poverty_gap").sum()
        deep_poverty_gap = self.simulation.calculate("deep_poverty_gap").sum()
        return in_poverty, person_in_poverty, person_in_deep_poverty, poverty_gap, deep_poverty_gap
    
    def calculate_weights(self):
        person_weight = self.simulation.calculate("person_weight").astype(float).tolist()
        household_weight = self.simulation.calculate("household_weight").astype(float).tolist()

        return person_weight, household_weight
    
    def calculate_labor_supply_responses(self):
        result = {
            "substitution_lsr": 0,
            "income_lsr": 0,
            "budgetary_impact_lsr": 0,
            "income_lsr_hh": (self.household_count_people * 0).astype(float).tolist(),
            "substitution_lsr_hh": (self.household_count_people * 0).astype(float).tolist(),
        }

        if not self._has_behavioral_response():
            return result

        result.update({
            "substitution_lsr": self.simulation.calculate("substitution_elasticity_lsr").sum(),
            "income_lsr": self.simulation.calculate("income_elasticity_lsr").sum(),
            "income_lsr_hh": self.simulation.calculate("income_elasticity_lsr", map_to="household").astype(float).tolist(),
            "substitution_lsr_hh": self.simulation.calculate("substitution_elasticity_lsr", map_to="household").astype(float).tolist(),
        })
        
        return result
    
    def _has_behavioral_response(self) -> bool:
        return (
            "employment_income_behavioral_response" in self.simulation.tax_benefit_system.variables
            and any(self.simulation.calculate("employment_income_behavioral_response") != 0)
        )
    
    def calculate_lsr_working_hours(self):
        if self.country_id != "us":
            return {
                "weekly_hours": 0,
                "weekly_hours_income_effect": 0,
                "weekly_hours_substitution_effect": 0
            }

        return {
            "weekly_hours": self.simulation.calculate("weekly_hours_worked").sum(),
            "weekly_hours_income_effect": self.simulation.calculate("weekly_hours_worked_behavioural_response_income_elasticity").sum(),
            "weekly_hours_substitution_effect": self.simulation.calculate("weekly_hours_worked_behavioural_response_substitution_elasticity").sum()
        }

    def calculate_uk_programs(self) -> Dict[str, float]:
        if self.country_id != "uk":
            return {}
            
        return {
            program.name: self.simulation.calculate(program.name, map_to="household").sum() 
            * (1 if program.is_positive else -1)
            for program in UKPrograms.PROGRAMS
        }
    

    
def compute_general_economy(simulation, country_id: str) -> Dict:
    task_manager = GeneralEconomyTask(simulation, country_id)

    total_tax, total_spending = task_manager.calculate_tax_and_spending()
    gini, top_10_share, top_1_share = task_manager.calculate_inequality_metrics()
    wealth, wealth_decile = task_manager.calculate_wealth_metrics()
    is_male, race, age = task_manager.calculate_demographic_metrics()
    labor_supply_responses = task_manager.calculate_labor_supply_responses()
    lsr_working_hours = task_manager.calculate_lsr_working_hours()
    in_poverty, person_in_poverty, person_in_deep_poverty, poverty_gap, deep_poverty_gap = task_manager.calculate_poverty_metrics()
    total_net_income, employment_income_hh, self_employment_income_hh = task_manager.calculate_income_breakdown_metrics()
    household_net_income, equiv_household_net_income, household_income_decile, household_market_income = task_manager.calculate_household_income_metrics()
    person_weight, household_weight = task_manager.calculate_weights()

    if country_id == "uk":
        uk_programs = task_manager.calculate_uk_programs()
    else:
        uk_programs = {}

    if country_id == "us":
        try:
            total_state_tax = simulation.calculate("household_state_income_tax").sum()
        except:
            total_state_tax = 0
    
    result = {
        "total_net_income": total_net_income,
        "employment_income_hh": employment_income_hh,
        "self_employment_income_hh": self_employment_income_hh,
        "total_tax": total_tax,
        "total_state_tax": total_state_tax,
        "total_benefits": total_spending,
        "household_net_income": household_net_income,
        "equiv_household_net_income": equiv_household_net_income,
        "household_income_decile": household_income_decile,
        "household_market_income": household_market_income,
        "household_wealth_decile": wealth_decile,
        "household_wealth": wealth,
        "in_poverty": in_poverty,
        "person_in_poverty": person_in_poverty,
        "person_in_deep_poverty": person_in_deep_poverty,
        "poverty_gap": poverty_gap,
        "deep_poverty_gap": deep_poverty_gap,
        "person_weight": person_weight,
        "household_weight": household_weight,
        "household_count_people": task_manager.household_count_people.astype(int).tolist(),
        "gini": float(gini),
        "top_10_percent_share": float(top_10_share),
        "top_1_percent_share": float(top_1_share),
        "is_male": is_male,
        "race": race,
        "age": age,
        **labor_supply_responses,
        **lsr_working_hours,
        "type": "general",
        "programs": uk_programs, 
    }

    return result