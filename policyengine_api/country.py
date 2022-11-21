import importlib
import math
import json
from typing import List, Type, Tuple
from flask import Response
from policyengine_core.taxbenefitsystems import TaxBenefitSystem
from policyengine_core.parameters import (
    Parameter,
    ParameterNode,
    ParameterScale,
    get_parameter,
)
from policyengine_core.enums import Enum
from policyengine_api.utils import (
    get_requested_computations,
    get_safe_json,
    create_reform,
)


class PolicyEngineCountry:
    def __init__(self, country_package_name: str):
        self.country_package_name = country_package_name
        self.country_package = importlib.import_module(country_package_name)
        self.tax_benefit_system: TaxBenefitSystem = (
            self.country_package.CountryTaxBenefitSystem()
        )

    def calculate(
        self, household: dict, policy: List[Tuple[str, str, float]]
    ) -> dict:
        system = self.tax_benefit_system
        if len(policy) > 0:
            system = system.clone()
            for parameter_name, time_period, value in policy:
                parameter = get_parameter(system.parameters, parameter_name)
                parameter.update(period=time_period, value=value)

        simulation = self.country_package.Simulation(
            tax_benefit_system=system,
            situation=household,
        )

        household = json.loads(json.dumps(household))

        requested_computations = get_requested_computations(household)

        for (
            entity_plural,
            entity_id,
            variable_name,
            period,
        ) in requested_computations:
            try:
                variable = system.get_variable(variable_name)
                result = simulation.calculate(variable_name, period)
                population = simulation.get_population(entity_plural)
                if "axes" in household:
                    count_entities = len(household[entity_plural])
                    entity_index = 0
                    for _entity_id in household[entity_plural].keys():
                        if _entity_id == entity_id:
                            break
                        entity_index += 1
                    result = (
                        result.astype(float)
                        .reshape((-1, count_entities))
                        .T[entity_index]
                        .tolist()
                    )
                    # If the result contains infinities, throw an error
                    if any([math.isinf(value) for value in result]):
                        raise ValueError("Infinite value")
                    else:
                        household[entity_plural][entity_id][variable_name][
                            period
                        ] = result
                else:
                    entity_index = population.get_index(entity_id)
                    if variable.value_type == Enum:
                        entity_result = result.decode()[entity_index].name
                    elif variable.value_type == float:
                        entity_result = float(str(result[entity_index]))
                        # Convert infinities to JSON infinities
                        if entity_result == float("inf"):
                            entity_result = "Infinity"
                        elif entity_result == float("-inf"):
                            entity_result = "-Infinity"
                    elif variable.value_type == str:
                        entity_result = str(result[entity_index])
                    else:
                        entity_result = result.tolist()[entity_index]

                    household[entity_plural][entity_id][variable_name][
                        period
                    ] = entity_result
            except:
                pass
        return household

    def get_economy_data(self, policy: dict) -> dict:
        simulation = self.country_package.Microsimulation(
            reform=create_reform(policy),
        )

        return {
            "total_net_income": simulation.calculate(
                "household_net_income"
            ).sum(),
            "total_tax": simulation.calculate("household_tax").sum(),
            "total_benefits": simulation.calculate("household_benefits").sum(),
            "household_net_income": simulation.calculate(
                "household_net_income"
            )
            .astype(float)
            .tolist(),
            "equiv_household_net_income": simulation.calculate(
                "equiv_household_net_income",
            ).astype(float)
            .tolist(),
            "household_income_decile": simulation.calculate("household_income_decile")
            .astype(int)
            .tolist(),
            "in_poverty": simulation.calculate("in_poverty")
            .astype(bool)
            .tolist(),
            "poverty_gap": simulation.calculate("poverty_gap")
            .astype(float)
            .tolist(),
            "household_weight": simulation.calculate("household_weight")
            .astype(float)
            .tolist(),
            "household_count_people": simulation.calculate(
                "household_count_people"
            )
            .astype(int)
            .tolist(),
        }


COUNTRIES = {
    "uk": PolicyEngineCountry("policyengine_uk"),
    "us": PolicyEngineCountry("policyengine_us"),
}

def validate_country(country_id: str) -> dict:
    if country_id not in COUNTRIES:
        body = dict(status="error", message=f"Country {country_id} not found. Available countries are: {', '.join(COUNTRIES.keys())}")
        return Response(body, status=404)
    return None