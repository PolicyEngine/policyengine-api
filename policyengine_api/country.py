import importlib
import dpath
import json
from typing import List, Type, Tuple
from policyengine_core.taxbenefitsystems import TaxBenefitSystem
from policyengine_core.parameters import Parameter, ParameterNode, ParameterScale, get_parameter
from policyengine_core.enums import Enum
from policyengine_api.utils import get_requested_computations

class PolicyEngineCountry:
    def __init__(self, country_package_name: str, name: str):
        self.country_package_name = country_package_name
        self.country_package = importlib.import_module(country_package_name)
        self.tax_benefit_system: TaxBenefitSystem = self.country_package.CountryTaxBenefitSystem()
        self.variable_data = self.build_variables()
        self.parameter_data = self.build_parameters()
    
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
            }
        return variable_data
    
    def build_parameters(self) -> dict:
        parameters = self.tax_benefit_system.parameters
        parameter_data = {}
        for parameter in parameters.get_descendants():
            if isinstance(parameter, Parameter):
                parameter_data[parameter.name] = {
                    "type": "parameter",
                    "description": parameter.description,
                    "label": parameter.metadata.get("label"),
                    "unit": parameter.metadata.get("unit"),
                    "period": parameter.metadata.get("period"),
                    "values": {
                        value_at_instant.instant_str: value_at_instant.value
                        for value_at_instant in parameter.values_list
                    }
                }
            elif isinstance(parameter, ParameterNode) and parameter.metadata.get("breakdown") is not None:
                count_levels = len(parameter.metadata["breakdown"])
                level_fields = []
                for i in range(count_levels):
                    node = parameter
                    for _ in range(i):
                        node = list(parameter.children.values())[0]
                    breakdown_key = parameter.metadata["breakdown"][i]
                    if isinstance(breakdown_key, str) and breakdown_key in self.tax_benefit_system.variables:
                        enum_type: Type[Enum] = self.tax_benefit_system.variables[breakdown_key].possible_values
                        level_data = [dict(name=enum.name, label=enum.value) for enum in enum_type]
                    else:
                        level_data = [dict(name=child, label=child) for child in node.children]
                    level_fields.append(level_data)
                parameter_data[parameter.name] = {
                    "type": "parameterBreakdown",
                    "description": parameter.description,
                    "label": parameter.metadata.get("label"),
                    "unit": parameter.metadata.get("unit"),
                    "period": parameter.metadata.get("period"),
                    "children": level_fields,
                }
            elif isinstance(parameter, ParameterScale):
                parameter_data[parameter.name] = {
                    "type": "parameterScale",
                    "description": parameter.description,
                    "label": parameter.metadata.get("label"),
                    "amount_unit": parameter.metadata.get("amount_unit"),
                    "rate_unit": parameter.metadata.get("rate_unit"),
                    "threshold_unit": parameter.metadata.get("threshold_unit"),
                    "amount_period": parameter.metadata.get("amount_period"),
                    "rate_period": parameter.metadata.get("rate_period"),
                    "threshold_period": parameter.metadata.get("threshold_period"),
                    "brackets": [
                        {
                            "amount": bracket.amount.name if hasattr(bracket, "amount") else None,
                            "rate": bracket.rate.name if hasattr(bracket, "rate") else None,
                            "threshold": bracket.threshold.name if hasattr(bracket, "threshold") else None,
                        }
                        for bracket in parameter.brackets
                    ],
                }
        return parameter_data
    
    def calculate(self, household: dict, policy: List[Tuple[str, str, float]]) -> dict:
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

        for entity_plural, entity_id, variable_name, period in requested_computations:
            variable = system.get_variable(variable_name)
            result = simulation.calculate(variable_name, period)
            population = simulation.get_population(entity_plural)
            entity_index = population.get_index(entity_id)

            if variable.value_type == Enum:
                entity_result = result.decode()[entity_index].name
            elif variable.value_type == float:
                entity_result = float(str(result[entity_index]))
            elif variable.value_type == str:
                entity_result = str(result[entity_index])
            else:
                entity_result = result.tolist()[entity_index]
            
            household[entity_plural][entity_id][variable_name][period] = entity_result

        return household
