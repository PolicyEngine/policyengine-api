import importlib
from flask import Response
import json
from policyengine_core.taxbenefitsystems import TaxBenefitSystem
from typing import Union
from policyengine_api.utils import get_safe_json
from policyengine_core.parameters import (
    ParameterNode,
    Parameter,
    ParameterScale,
    ParameterScaleBracket,
)
from policyengine_core.parameters import get_parameter
import pkg_resources
from policyengine_core.model_api import Reform, Enum
from policyengine_core.periods import instant
import dpath
import math
print(f"Initialising country packages...")
import policyengine_uk
import policyengine_us
import policyengine_canada
import policyengine_ng


class PolicyEngineCountry:
    def __init__(self, country_package_name: str, country_id: str):
        self.country_package_name = country_package_name
        self.country_id = country_id
        self.country_package = importlib.import_module(country_package_name)
        self.tax_benefit_system: TaxBenefitSystem = (
            self.country_package.CountryTaxBenefitSystem()
        )
        self.build_metadata()

    def build_metadata(self):
        self.metadata = dict(
            status="ok",
            message=None,
            result=dict(
                variables=self.build_variables(),
                parameters=self.build_parameters(),
                entities=self.build_entities(),
                variableModules=self.tax_benefit_system.variable_module_metadata,
                economy_options=self.build_microsimulation_options(),
                current_law_id={
                    "uk": 1,
                    "us": 2,
                    "ca": 3,
                    "ng": 4,
                }[self.country_id],
                basicInputs=self.tax_benefit_system.basic_inputs,
                modelled_policies=self.tax_benefit_system.modelled_policies,
                version=pkg_resources.get_distribution(
                    self.country_package_name
                ).version,
            ),
        )
    
    def build_microsimulation_options(
        self
    ) -> dict:
        # { region: [{ name: "uk", label: "the UK" }], time_period: [{ name: 2022, label: "2022", ... }] }
        options = dict()
        if self.country_id == "uk":
            region = [
                dict(name="uk", label="the UK"),
                dict(name="eng", label="England"),
                dict(name="scot", label="Scotland"),
                dict(name="wales", label="Wales"),
                dict(name="ni", label="Northern Ireland"),
            ]
            time_period = [
                dict(name=2023, label="2023"),
                dict(name=2024, label="2024"),
                dict(name=2022, label="2022"),
            ]
            options["region"] = region
            options["time_period"] = time_period
        elif self.country_id == "us":
            region = [
                dict(name="us", label="the US"),
                dict(name="ak", label="Alaska"),
                dict(name="al", label="Alabama"),
                dict(name="ar", label="Arkansas"),
                dict(name="az", label="Arizona"),
                dict(name="ca", label="California"),
                dict(name="co", label="Colorado"),
                dict(name="ct", label="Connecticut"),
                dict(name="dc", label="District of Columbia"),
                dict(name="de", label="Delaware"),
                dict(name="fl", label="Florida"),
                dict(name="ga", label="Georgia"),
                dict(name="hi", label="Hawaii"),
                dict(name="ia", label="Iowa"),
                dict(name="id", label="Idaho"),
                dict(name="il", label="Illinois"),
                dict(name="in", label="Indiana"),
                dict(name="ks", label="Kansas"),
                dict(name="ky", label="Kentucky"),
                dict(name="la", label="Louisiana"),
                dict(name="ma", label="Massachusetts"),
                dict(name="md", label="Maryland"),
                dict(name="me", label="Maine"),
                dict(name="mi", label="Michigan"),
                dict(name="mn", label="Minnesota"),
                dict(name="mo", label="Missouri"),
                dict(name="ms", label="Mississippi"),
                dict(name="mt", label="Montana"),
                dict(name="nc", label="North Carolina"),
                dict(name="nd", label="North Dakota"),
                dict(name="nv", label="Nevada"),
                dict(name="ny", label="New York"),
                dict(name="oh", label="Ohio"),
                dict(name="or", label="Oregon"),
                dict(name="pa", label="Pennsylvania"),
                dict(name="ri", label="Rhode Island"),
                dict(name="sd", label="South Dakota"),
                dict(name="tn", label="Tennessee"),
                dict(name="tx", label="Texas"),
                dict(name="ut", label="Utah"),
                dict(name="va", label="Virginia"),
                dict(name="vt", label="Vermont"),
                dict(name="wa", label="Washington"),
                dict(name="wi", label="Wisconsin"),
                dict(name="wv", label="West Virginia"),
            ]
            time_period = [
                dict(name=2023, label="2023"),
                dict(name=2024, label="2024"),
                dict(name=2022, label="2022"),
            ]
            options["region"] = region
            options["time_period"] = time_period
        elif self.country_id == "ca":
            region = [
                dict(name="ca", label="Canada"),
            ]
            time_period = [
                dict(name=2023, label="2023"),
            ]
            options["region"] = region
            options["time_period"] = time_period
        elif self.country_id == "ng":
            region = [
                dict(name="ng", label="Nigeria"),
            ]
            time_period = [
                dict(name=2023, label="2023"),
            ]
            options["region"] = region
            options["time_period"] = time_period
        return options


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
                "hidden_input": variable.hidden_input,
            }
            if variable.value_type.__name__ == "Enum":
                variable_data[variable_name]["possibleValues"] = [
                    dict(value=value.name, label=value.value)
                    for value in variable.possible_values
                ]
                variable_data[variable_name][
                    "defaultValue"
                ] = variable.default_value.name
        return variable_data


    def build_parameters(self) -> dict:
        parameters = self.tax_benefit_system.parameters
        parameter_data = {}
        for parameter in parameters.get_descendants():
            if "gov" != parameter.name[:3]:
                continue
            end_name = parameter.name.split(".")[-1]
            if isinstance(parameter, ParameterScale):
                parameter_data[parameter.name] = {
                    "type": "parameterNode",
                    "parameter": parameter.name,
                    "description": parameter.description,
                    "label": parameter.metadata.get(
                        "label", end_name.replace("_", " ")
                    ),
                }
            elif isinstance(parameter, ParameterScaleBracket):
                bracket_index = int(
                    parameter.name[parameter.name.index("[") + 1 : -1]
                )
                # Set the label to 'first bracket' for the first bracket, 'second bracket' for the second, etc.
                bracket_label = f"bracket {bracket_index + 1}"
                parameter_data[parameter.name] = {
                    "type": "parameterNode",
                    "parameter": parameter.name,
                    "description": parameter.description,
                    "label": parameter.metadata.get("label", bracket_label),
                }
            elif isinstance(parameter, Parameter):
                parameter_data[parameter.name] = {
                    "type": "parameter",
                    "parameter": parameter.name,
                    "description": parameter.description,
                    "label": parameter.metadata.get(
                        "label", end_name.replace("_", " ")
                    ),
                    "unit": parameter.metadata.get("unit"),
                    "period": parameter.metadata.get("period"),
                    "values": {
                        value_at_instant.instant_str: get_safe_json(
                            value_at_instant.value
                        )
                        for value_at_instant in parameter.values_list
                    },
                    "economy": parameter.metadata.get("economy", True),
                    "household": parameter.metadata.get("household", True),
                }
            elif isinstance(parameters, ParameterNode):
                parameter_data[parameter.name] = {
                    "type": "parameterNode",
                    "parameter": parameter.name,
                    "description": parameter.description,
                    "label": parameter.metadata.get(
                        "label", end_name.replace("_", " ")
                    ),
                    "economy": parameter.metadata.get("economy", True),
                    "household": parameter.metadata.get("household", True),
                }
        return parameter_data


    def build_entities(self) -> dict:
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
        self, household: dict, reform: dict
    ) -> dict:
        if len(reform.keys()) > 0:
            system = self.tax_benefit_system.clone()
            for parameter_name in reform:
                for time_period, value in reform[parameter_name].items():
                    start_instant, end_instant = time_period.split(".")
                    parameter = get_parameter(system.parameters, parameter_name)
                    node_type = type(parameter.values_list[-1].value)
                    if node_type == int:
                        node_type = float
                    try:
                        value = float(value)
                    except:
                        pass
                    parameter.update(
                        start=instant(start_instant),
                        stop=instant(end_instant),
                        value=node_type(value),
                    )
        else:
            system = self.tax_benefit_system

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
            except Exception as e:
                if "axes" in household:
                    pass
                else:
                    household[entity_plural][entity_id][variable_name][
                        period
                    ] = None

        return household

    

def create_policy_reform(policy_data: dict) -> dict:
    """
    Create a policy reform.

    Args:
        policy_data (dict): The policy data.

    Returns:
        dict: The reform.
    """

    def modify_parameters(parameters: ParameterNode) -> ParameterNode:
        for path, values in policy_data.items():
            node = parameters
            for step in path.split("."):
                if "[" in step:
                    step, index = step.split("[")
                    index = int(index[:-1])
                    node = node.children[step].brackets[index]
                else:
                    node = node.children[step]
            for period, value in values.items():
                start, end = period.split(".")
                node_type = type(node.values_list[-1].value)
                if node_type == int:
                    node_type = float  # '0' is of type int by default, but usually we want to cast to float.
                node.update(
                    start=instant(start),
                    stop=instant(end),
                    value=node_type(value),
                )

        return parameters

    class reform(Reform):
        def apply(self):
            self.modify_parameters(modify_parameters)

    return reform

def get_requested_computations(household: dict):
    requested_computations = dpath.util.search(
        household,
        "*/*/*/*",
        afilter=lambda t: t is None,
        yielded=True,
    )
    requested_computation_data = []

    for computation in requested_computations:
        path = computation[0]
        entity_plural, entity_id, variable_name, period = path.split("/")
        requested_computation_data.append(
            (entity_plural, entity_id, variable_name, period)
        )

    return requested_computation_data



COUNTRIES = {
    "uk": PolicyEngineCountry("policyengine_uk", "uk"),
    "us": PolicyEngineCountry("policyengine_us", "us"),
    "ca": PolicyEngineCountry("policyengine_canada", "ca"),
    "ng": PolicyEngineCountry("policyengine_ng", "ng"),
}


def validate_country(country_id: str) -> Union[None, Response]:
    """Validate that a country ID is valid. If not, return a 404 response.

    Args:
        country_id (str): The country ID to validate.

    Returns:

    """
    if country_id not in COUNTRIES:
        body = dict(
            status="error",
            message=f"Country {country_id} not found. Available countries are: {', '.join(COUNTRIES.keys())}",
        )
        return Response(json.dumps(body), status=404)
    return None

