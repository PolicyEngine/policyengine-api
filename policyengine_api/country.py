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
import policyengine_uk
import policyengine_us
import policyengine_canada
import policyengine_ng
import policyengine_il
from policyengine_api.data import local_database
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS


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
                    "il": 5,
                }[self.country_id],
                basicInputs=self.tax_benefit_system.basic_inputs,
                modelled_policies=self.tax_benefit_system.modelled_policies,
                version=pkg_resources.get_distribution(
                    self.country_package_name
                ).version,
            ),
        )

    def build_microsimulation_options(self) -> dict:
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
                dict(name=2024, label="2024"),
                dict(name=2025, label="2025"),
                dict(name=2026, label="2026"),
                dict(name=2027, label="2027"),
                dict(name=2028, label="2028"),
                dict(name=2029, label="2029"),
            ]
            options["region"] = region
            options["time_period"] = time_period
        elif self.country_id == "us":
            region = [
                dict(name="us", label="the US"),
                dict(name="enhanced_us", label="the US (enhanced CPS)"),
                dict(name="al", label="Alabama"),
                dict(name="ak", label="Alaska"),
                dict(name="az", label="Arizona"),
                dict(name="ar", label="Arkansas"),
                dict(name="ca", label="California"),
                dict(name="co", label="Colorado"),
                dict(name="ct", label="Connecticut"),
                dict(name="de", label="Delaware"),
                dict(name="dc", label="District of Columbia"),
                dict(name="fl", label="Florida"),
                dict(name="ga", label="Georgia"),
                dict(name="hi", label="Hawaii"),
                dict(name="id", label="Idaho"),
                dict(name="il", label="Illinois"),
                dict(name="in", label="Indiana"),
                dict(name="ia", label="Iowa"),
                dict(name="ks", label="Kansas"),
                dict(name="ky", label="Kentucky"),
                dict(name="la", label="Louisiana"),
                dict(name="me", label="Maine"),
                dict(name="md", label="Maryland"),
                dict(name="ma", label="Massachusetts"),
                dict(name="mi", label="Michigan"),
                dict(name="mn", label="Minnesota"),
                dict(name="ms", label="Mississippi"),
                dict(name="mo", label="Missouri"),
                dict(name="mt", label="Montana"),
                dict(name="ne", label="Nebraska"),
                dict(name="nv", label="Nevada"),
                dict(name="nh", label="New Hampshire"),
                dict(name="nj", label="New Jersey"),
                dict(name="nm", label="New Mexico"),
                dict(name="ny", label="New York"),
                dict(name="nyc", label="New York City"),  # Region, not State
                dict(name="nc", label="North Carolina"),
                dict(name="nd", label="North Dakota"),
                dict(name="oh", label="Ohio"),
                dict(name="ok", label="Oklahoma"),
                dict(name="or", label="Oregon"),
                dict(name="pa", label="Pennsylvania"),
                dict(name="ri", label="Rhode Island"),
                dict(name="sc", label="South Carolina"),
                dict(name="sd", label="South Dakota"),
                dict(name="tn", label="Tennessee"),
                dict(name="tx", label="Texas"),
                dict(name="ut", label="Utah"),
                dict(name="vt", label="Vermont"),
                dict(name="va", label="Virginia"),
                dict(name="wa", label="Washington"),
                dict(name="wv", label="West Virginia"),
                dict(name="wi", label="Wisconsin"),
                dict(name="wy", label="Wyoming"),
            ]
            time_period = [
                dict(name=2034, label="2034"),
                dict(name=2033, label="2033"),
                dict(name=2032, label="2032"),
                dict(name=2031, label="2031"),
                dict(name=2030, label="2030"),
                dict(name=2029, label="2029"),
                dict(name=2028, label="2028"),
                dict(name=2027, label="2027"),
                dict(name=2026, label="2026"),
                dict(name=2025, label="2025"),
                dict(name=2024, label="2024"),
                dict(name=2023, label="2023"),
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
        elif self.country_id == "il":
            region = [
                dict(name="il", label="Israel"),
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
                "defaultValue": (
                    variable.default_value
                    if isinstance(variable.default_value, (int, float, bool))
                    else None
                ),
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
                parameter.propagate_units()
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

    # Modify calculate function to Set situation.tracer to True
    # 1. Flatten household_net_income into an array via the utility function
    # 2. When calculating each variable, check if the variable is within that array and that its value isn’t equal to variable.default_value;
    # 3. If both are true, save its tracer log to the local tracers table (via local_database; no need to save to standard db) (more below)

    # check if the variable being calculated matches the output of the get_all_variables function,
    # and if so, to write the tracer log to the local_database object.

    def calculate(self, household: dict, reform: Union[dict, None] = None):
        if reform is not None and len(reform.keys()) > 0:
            system = self.tax_benefit_system.clone()
            for parameter_name in reform:
                for time_period, value in reform[parameter_name].items():
                    start_instant, end_instant = time_period.split(".")
                    parameter = get_parameter(
                        system.parameters, parameter_name
                    )
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
                traced_variables = get_all_variables(
                    "household_net_income", system, period, []
                )

                variable = system.get_variable(variable_name)
                simulation.trace = True
                result = simulation.calculate(variable_name, period)
                population = simulation.get_population(entity_plural)

                # Check if the variable is within the traced variables array
                if variable_name in traced_variables:
                    entity_index = population.get_index(entity_id)

                    # Get the calculated value for this entity
                    if variable.value_type == Enum:
                        calculated_value = result.decode()[entity_index].name
                    elif variable.value_type in (float, int):
                        calculated_value = float(str(result[entity_index]))
                    elif variable.value_type == str:
                        calculated_value = str(result[entity_index])
                    else:
                        calculated_value = result.tolist()[entity_index]

                    # Get the tracer output
                    tracer_output = simulation.tracer.computation_log
                    log_lines = tracer_output.lines(aggregate=False, max_depth=4)
                    log_str = "\n".join(log_lines)

                    # Check if the calculated value isn't equal to the default value
                    # If it's not default, write to local database
                    if calculated_value != variable.default_value:
                      local_database.query(
                          """
                          INSERT INTO tracers
                          (household_id, policy_id, country_id, api_version, tracer_output, variable_name)
                          VALUES (?, ?, ?, ?, ?, ?)
                          """,
                          (
                              household.get("id", 0),
                              reform.get("id", 0) if reform else 0,
                              self.country_id,
                              COUNTRY_PACKAGE_VERSIONS[self.country_id],
                              log_str,
                              variable_name,
                          ),
                      )

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
                    print(
                        f"Error computing {variable_name} for {entity_id}: {e}"
                    )

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
    "il": PolicyEngineCountry("policyengine_il", "il"),
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


# Write a utility function to take a given variable name and recurse through its adds and subtracts values and append each given variable to an array;
# this function will also need to handle list parameters, which can be accessed through the system’s get_parameter function, I believe,
# and can be tested for by checking if the adds is of type str
# write a recursive function here that, when there is an adds and/or a subtracts, calls get_all_variables on that next tier downward, until eventually you hit some marker of there being no more levels.


def get_all_variables(
    variable_name: str, system: TaxBenefitSystem, period, variables: list
) -> list:
    """
    Get all variables from a given variable name.

    Args:
        variable_name (str): The variable name.
        system (TaxBenefitSystem): The tax benefit system.
        period (str): The period.
        variables (list): The list of variables.

    Returns:
        list: The list of variables.
    """

    variable = system.get_variable(variable_name)

    # adds and subtracts can be three things:
    # a string (if a list param - will need to fetch param,
    # find value at period, then recurse downward)
    # a list (if a list of values - will need to recurse)
    # None (if there are no more levels)

    if variable is None:
        return

    adds = variable.adds
    if isinstance(adds, str):
        list_param = get_parameter(system.parameters, adds)
        list_param_vars = list_param.get_at_instant(period)
        for var in list_param_vars:
            variables.append(var)
            get_all_variables(var, system, period, variables)
    elif isinstance(adds, list):
        for add in adds:
            variables.append(add)
            get_all_variables(add, system, period, variables)

    subtracts = variable.subtracts
    if isinstance(subtracts, str):
        list_param = get_parameter(system.parameters, subtracts)
        list_param_vars = list_param.get_at_instant(period)
        for var in list_param_vars:
            variables.append(var)
            get_all_variables(var, system, period, variables)
    elif isinstance(subtracts, list):
        for subtract in subtracts:
            variables.append(subtract)
            get_all_variables(subtract, system, period, variables)

    return variables
