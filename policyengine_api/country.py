import importlib
import math
import json
from typing import List, Type, Tuple
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
    sanitise_parameter_value,
    create_reform,
)


class PolicyEngineCountry:
    def __init__(self, country_package_name: str):
        self.country_package_name = country_package_name
        self.country_package = importlib.import_module(country_package_name)
        self.tax_benefit_system: TaxBenefitSystem = (
            self.country_package.CountryTaxBenefitSystem()
        )
        self.variable_data = self.build_variables()
        self.parameter_data = self.build_parameters()
        self.entities_data = self.build_entities()
        self.variable_module_metadata = (
            self.tax_benefit_system.variable_module_metadata
        )

    def build_variables(self) -> dict:
        variables = self.tax_benefit_system.variables
        variable_data = {}
        for variable_name, variable in variables.items():
            variable_data[variable_name] = {
                "documentation": variable.documentation,
                "entity": variable.entity.key,
                "valueType": variable.value_type.__name__,
                "definitionPeriod": variable.definition_period,
                "name": variable_name,
                "label": variable.label,
                "category": variable.category,
                "unit": variable.unit,
                "moduleName": variable.module_name,
                "indexInModule": variable.index_in_module,
                "isInputVariable": variable.is_input_variable(),
                "defaultValue": variable.default_value
                if isinstance(variable.default_value, (int, float, bool))
                else None,
                "adds": variable.adds,
                "subtracts": variable.subtracts,
            }
        return variable_data

    def build_parameters(self) -> dict:
        parameters = self.tax_benefit_system.parameters
        parameter_data = {}
        for parameter in parameters.get_descendants():
            if "gov." != parameter.name[:4]:
                continue
            if isinstance(parameter, Parameter):
                parameter_data[parameter.name] = {
                    "type": "parameter",
                    "parameter": parameter.name,
                    "description": parameter.description,
                    "label": parameter.metadata.get("label"),
                    "unit": parameter.metadata.get("unit"),
                    "period": parameter.metadata.get("period"),
                    "values": {
                        value_at_instant.instant_str: sanitise_parameter_value(
                            value_at_instant.value
                        )
                        for value_at_instant in parameter.values_list
                    },
                }
            elif isinstance(parameters, ParameterNode):
                parameter_data[parameter.name] = {
                    "type": "parameterNode",
                    "parameter": parameter.name,
                    "description": parameter.description,
                    "label": parameter.metadata.get("label"),
                }
        return parameter_data

    def build_entities(self):
        data = {}
        for entity in self.tax_benefit_system.entities:
            entity_data = {
                "plural": entity.plural,
                "label": entity.label,
                "doc": entity.doc,
                "is_person": entity.is_person,
                "key": entity.key,
            }
            if hasattr(entity, "roles"):
                entity_data["roles"] = {
                    role.key: {
                        "plural": role.plural,
                        "label": role.label,
                        "doc": role.doc,
                    }
                    for role in entity.roles
                }
            else:
                entity_data["roles"] = {}
            data[entity.key] = entity_data
        return data

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
            "income_decile": simulation.calculate("income_decile")
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
