import importlib
from flask import Response
import json
from policyengine_core.taxbenefitsystems import TaxBenefitSystem
from typing import Union, Optional
from policyengine_api.utils import get_safe_json
from policyengine_core.parameters import (
    ParameterNode,
    Parameter,
    ParameterScale,
    ParameterScaleBracket,
)
from policyengine_core.parameters import get_parameter
from importlib.metadata import version as get_package_version
from policyengine_core.model_api import Reform, Enum
from policyengine_core.periods import instant
import dpath
import math
import pandas as pd
from pathlib import Path
from policyengine_api.data.congressional_districts import (
    build_congressional_district_metadata,
)

# Note: The following policyengine_[xx] imports are probably redundant.
# These modules are imported dynamically in the __init__ function below.
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
            version=get_package_version(
                self.country_package_name.replace("_", "-")
            ),
        )

    def build_microsimulation_options(self) -> dict:
        # { region: [{ name: "uk", label: "the UK" }], time_period: [{ name: 2022, label: "2022", ... }] }
        options = dict()
        if self.country_id == "uk":
            constituency_names_path = (
                Path(__file__).parent / "data" / "constituencies_2024.csv"
            )
            constituency_names = pd.read_csv(constituency_names_path)
            constituency_names = constituency_names.sort_values("name")
            region = [
                dict(name="uk", label="the UK", type="national"),
                dict(name="country/england", label="England", type="country"),
                dict(
                    name="country/scotland", label="Scotland", type="country"
                ),
                dict(name="country/wales", label="Wales", type="country"),
                dict(
                    name="country/ni", label="Northern Ireland", type="country"
                ),
            ]
            for i in range(len(constituency_names)):
                region.append(
                    dict(
                        name=f"constituency/{constituency_names.iloc[i]['name']}",
                        label=constituency_names.iloc[i]["name"],
                        type="constituency",
                    )
                )
            local_authority_names_path = (
                Path(__file__).parent / "data" / "local_authorities_2021.csv"
            )
            local_authority_names = pd.read_csv(local_authority_names_path)
            local_authority_names = local_authority_names.sort_values("name")
            for i in range(len(local_authority_names)):
                region.append(
                    dict(
                        name=f"local_authority/{local_authority_names.iloc[i]['name']}",
                        label=local_authority_names.iloc[i]["name"],
                        type="local_authority",
                    )
                )
            time_period = [
                dict(name=2024, label="2024"),
                dict(name=2025, label="2025"),
                dict(name=2026, label="2026"),
                dict(name=2027, label="2027"),
                dict(name=2028, label="2028"),
                dict(name=2029, label="2029"),
                dict(name=2030, label="2030"),
            ]
            datasets = [{}]
            options["region"] = region
            options["time_period"] = time_period
            options["datasets"] = datasets
        elif self.country_id == "us":
            region = [
                dict(name="us", label="the US", type="national"),
                dict(name="state/al", label="Alabama", type="state"),
                dict(name="state/ak", label="Alaska", type="state"),
                dict(name="state/az", label="Arizona", type="state"),
                dict(name="state/ar", label="Arkansas", type="state"),
                dict(name="state/ca", label="California", type="state"),
                dict(name="state/co", label="Colorado", type="state"),
                dict(name="state/ct", label="Connecticut", type="state"),
                dict(name="state/de", label="Delaware", type="state"),
                dict(
                    name="state/dc", label="District of Columbia", type="state"
                ),
                dict(name="state/fl", label="Florida", type="state"),
                dict(name="state/ga", label="Georgia", type="state"),
                dict(name="state/hi", label="Hawaii", type="state"),
                dict(name="state/id", label="Idaho", type="state"),
                dict(name="state/il", label="Illinois", type="state"),
                dict(name="state/in", label="Indiana", type="state"),
                dict(name="state/ia", label="Iowa", type="state"),
                dict(name="state/ks", label="Kansas", type="state"),
                dict(name="state/ky", label="Kentucky", type="state"),
                dict(name="state/la", label="Louisiana", type="state"),
                dict(name="state/me", label="Maine", type="state"),
                dict(name="state/md", label="Maryland", type="state"),
                dict(name="state/ma", label="Massachusetts", type="state"),
                dict(name="state/mi", label="Michigan", type="state"),
                dict(name="state/mn", label="Minnesota", type="state"),
                dict(name="state/ms", label="Mississippi", type="state"),
                dict(name="state/mo", label="Missouri", type="state"),
                dict(name="state/mt", label="Montana", type="state"),
                dict(name="state/ne", label="Nebraska", type="state"),
                dict(name="state/nv", label="Nevada", type="state"),
                dict(name="state/nh", label="New Hampshire", type="state"),
                dict(name="state/nj", label="New Jersey", type="state"),
                dict(name="state/nm", label="New Mexico", type="state"),
                dict(name="state/ny", label="New York", type="state"),
                dict(name="state/nc", label="North Carolina", type="state"),
                dict(name="state/nd", label="North Dakota", type="state"),
                dict(name="state/oh", label="Ohio", type="state"),
                dict(name="state/ok", label="Oklahoma", type="state"),
                dict(name="state/or", label="Oregon", type="state"),
                dict(name="state/pa", label="Pennsylvania", type="state"),
                dict(name="state/ri", label="Rhode Island", type="state"),
                dict(name="state/sc", label="South Carolina", type="state"),
                dict(name="state/sd", label="South Dakota", type="state"),
                dict(name="state/tn", label="Tennessee", type="state"),
                dict(name="state/tx", label="Texas", type="state"),
                dict(name="state/ut", label="Utah", type="state"),
                dict(name="state/vt", label="Vermont", type="state"),
                dict(name="state/va", label="Virginia", type="state"),
                dict(name="state/wa", label="Washington", type="state"),
                dict(name="state/wv", label="West Virginia", type="state"),
                dict(name="state/wi", label="Wisconsin", type="state"),
                dict(name="state/wy", label="Wyoming", type="state"),
            ]
            # Add all 436 congressional districts (435 voting + DC)
            region.extend(build_congressional_district_metadata())
            time_period = [
                dict(name=2035, label="2035"),
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
            datasets = [
                dict(
                    name="cps",
                    label="CPS",
                    title="Current Population Survey",
                    default=True,
                ),
                dict(
                    name="enhanced_cps",
                    label="enhanced CPS",
                    title="Enhanced Current Population Survey",
                    default=False,
                ),
            ]
            options["region"] = region
            options["time_period"] = time_period
            options["datasets"] = datasets
        elif self.country_id == "ca":
            region = [
                dict(name="ca", label="Canada"),
            ]
            time_period = [
                dict(name=2023, label="2023"),
            ]
            datasets = [{}]
            options["region"] = region
            options["time_period"] = time_period
            options["datasets"] = datasets
        elif self.country_id == "ng":
            region = [
                dict(name="ng", label="Nigeria"),
            ]
            time_period = [
                dict(name=2023, label="2023"),
            ]
            datasets = [{}]
            options["region"] = region
            options["time_period"] = time_period
            options["datasets"] = datasets
        elif self.country_id == "il":
            region = [
                dict(name="il", label="Israel"),
            ]
            time_period = [
                dict(name=2023, label="2023"),
            ]
            datasets = [{}]
            options["region"] = region
            options["time_period"] = time_period
            options["datasets"] = datasets
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

    def calculate(
        self,
        household: dict,
        reform: Union[dict, None],
        household_id: Optional[int] = None,
        policy_id: Optional[int] = None,
    ):
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

        simulation.trace = True
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
                    print(
                        f"Error computing {variable_name} for {entity_id}: {e}"
                    )

        tracer_output = simulation.tracer.computation_log
        log_lines = tracer_output.lines(aggregate=False, max_depth=10)
        log_json = json.dumps(log_lines)

        if household_id is not None and policy_id is not None:
            # write to local database
            local_database.query(
                """
                INSERT INTO tracers (household_id, policy_id, country_id, api_version, tracer_output)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    household_id,
                    policy_id,
                    self.country_id,
                    COUNTRY_PACKAGE_VERSIONS[self.country_id],
                    log_json,
                ),
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
                if node.values_list[-1].value is None:
                    node_type = float
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
