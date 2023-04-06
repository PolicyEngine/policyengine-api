from policyengine_api.country import (
    COUNTRIES,
    validate_country,
    PolicyEngineCountry,
)
from policyengine_api.utils import get_safe_json
from policyengine_core.parameters import (
    ParameterNode,
    Parameter,
    ParameterScale,
    ParameterScaleBracket,
)
import pkg_resources


def metadata(country_id: str):
    """
    /<country_id>/metadata (GET)

    Returns metadata about the country's tax and benefit system needed by the PolicyEngine web app.
    """
    country = COUNTRIES.get(country_id)
    country_not_found = validate_country(country_id)
    if country_not_found:
        return country_not_found
    if not hasattr(country, "metadata"):
        metadata_result = dict(
            status="ok",
            message=None,
            result=dict(
                variables=build_variables(country),
                parameters=build_parameters(country),
                entities=build_entities(country),
                variableModules=country.tax_benefit_system.variable_module_metadata,
                economy_options=build_microsimulation_options(
                    country, country_id
                ),
                current_law_id={
                    "uk": 1,
                    "us": 2,
                    "ca": 3,
                    "ng": 4,
                }[country_id],
                basicInputs=country.tax_benefit_system.basic_inputs,
                modelled_policies=country.tax_benefit_system.modelled_policies,
                version=pkg_resources.get_distribution(
                    country.country_package_name
                ).version,
            ),
        )
        country.metadata = metadata_result
    return country.metadata


def build_microsimulation_options(
    country: PolicyEngineCountry, country_id: str
) -> dict:
    # { region: [{ name: "uk", label: "the UK" }], time_period: [{ name: 2022, label: "2022", ... }] }
    options = dict()
    if country_id == "uk":
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
    elif country_id == "us":
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
    elif country_id == "ca":
        region = [
            dict(name="ca", label="Canada"),
        ]
        time_period = [
            dict(name=2023, label="2023"),
        ]
        options["region"] = region
        options["time_period"] = time_period
    elif country_id == "ng":
        region = [
            dict(name="ng", label="Nigeria"),
        ]
        time_period = [
            dict(name=2023, label="2023"),
        ]
        options["region"] = region
        options["time_period"] = time_period
    return options


def build_variables(country: PolicyEngineCountry) -> dict:
    variables = country.tax_benefit_system.variables
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


def build_parameters(country: PolicyEngineCountry) -> dict:
    parameters = country.tax_benefit_system.parameters
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


def build_entities(country: PolicyEngineCountry) -> dict:
    data = {}
    for entity in country.tax_benefit_system.entities:
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
