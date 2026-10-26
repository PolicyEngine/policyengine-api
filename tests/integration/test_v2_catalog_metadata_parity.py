"""Parity of catalog format 2's fields with the v1 ``/{country}/metadata`` document.

The catalog reads these fields from PolicyEngine.py's public records; the v1
document builds them from the country package's tax-benefit system. Each new
field must agree for the US and the UK. The check normalizes the installed
public models' metadata only, so it does not depend on the certified data
release that region publication reads.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from policyengine_api.data.v2.catalog.extraction import normalize_model_metadata

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from policyengine_api.data.v2.catalog.extraction import ModelMetadata

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_V2_CATALOG_COMPATIBILITY") != "1",
    reason=("loads the complete public catalog; set RUN_V2_CATALOG_COMPATIBILITY=1"),
)

COUNTRY_PACKAGES = {"us": "policyengine_us", "uk": "policyengine_uk"}


@pytest.fixture(scope="module", params=("us", "uk"))
def country_pair(request: pytest.FixtureRequest) -> tuple[ModelMetadata, Any]:
    """Return one country's normalized metadata and its v1 metadata builder."""
    import policyengine

    from policyengine_api.country import PolicyEngineCountry

    country_id = request.param
    metadata = normalize_model_metadata(
        country_id,
        getattr(policyengine, country_id).model,
        model_version_id=uuid4(),
    )
    return metadata, PolicyEngineCountry(COUNTRY_PACKAGES[country_id], country_id)


def _report(mismatches: list[str]) -> str:
    shown = "\n".join(mismatches[:20])
    return f"{len(mismatches)} mismatches, first {min(len(mismatches), 20)}:\n{shown}"


def _typed_enum_values(
    values: Iterable[Mapping[str, Any]],
) -> list[tuple[str, Any, str]]:
    """Return each enum value with its label and the label's type name.

    Comparing the type name as well keeps 1, 1.0 and True apart, which ``==``
    treats as equal.
    """
    return [
        (value["value"], value["label"], type(value["label"]).__name__)
        for value in values
    ]


def test_entities_and_basic_inputs_match_v1(
    country_pair: tuple[ModelMetadata, Any],
) -> None:
    metadata, v1_country = country_pair
    v1_entities = v1_country.metadata["entities"]

    assert [
        (entity.key, entity.plural, entity.is_person) for entity in metadata.entities
    ] == [
        (key, entity["plural"], entity["is_person"])
        for key, entity in v1_entities.items()
    ]
    assert list(metadata.basic_inputs) == (v1_country.metadata["basicInputs"])


def test_variable_flags_modules_enums_parts_units_and_periods_match_v1(
    country_pair: tuple[ModelMetadata, Any],
) -> None:
    metadata, v1_country = country_pair
    v1_variables = v1_country.metadata["variables"]
    mismatches: list[str] = []

    assert {variable.name for variable in metadata.variables} == set(v1_variables)
    for variable in metadata.variables:
        v1_variable = v1_variables[variable.name]
        enum_values = (
            _typed_enum_values(
                {"value": item.value, "label": item.label}
                for item in variable.enum_values
            )
            if variable.enum_values is not None
            else None
        )
        v1_enum_values = (
            _typed_enum_values(v1_variable["possibleValues"])
            if "possibleValues" in v1_variable
            else None
        )
        comparisons = {
            "is_input_variable": (
                variable.is_input_variable,
                v1_variable["isInputVariable"],
            ),
            "hidden_input": (variable.hidden_input, v1_variable["hidden_input"]),
            "module_name": (variable.module_name, v1_variable["moduleName"]),
            "enum_values": (enum_values, v1_enum_values),
            "unit": (variable.unit, v1_variable["unit"]),
            "definition_period": (
                variable.definition_period,
                v1_variable["definitionPeriod"],
            ),
            "adds_parameter_path": (
                variable.adds_parameter_path,
                v1_variable["adds"] if isinstance(v1_variable["adds"], str) else None,
            ),
            "subtracts_parameter_path": (
                variable.subtracts_parameter_path,
                v1_variable["subtracts"]
                if isinstance(v1_variable["subtracts"], str)
                else None,
            ),
        }
        mismatches.extend(
            f"{variable.name}.{field}: catalog {stored!r}, v1 {expected!r}"
            for field, (stored, expected) in comparisons.items()
            if stored != expected or type(stored) is not type(expected)
        )

    assert not mismatches, _report(mismatches)


def test_parameter_flags_match_v1(country_pair: tuple[ModelMetadata, Any]) -> None:
    metadata, v1_country = country_pair
    v1_parameters = {
        name: entry
        for name, entry in v1_country.metadata["parameters"].items()
        if entry["type"] == "parameter"
    }
    catalog_parameters = {
        parameter.name: parameter
        for parameter in metadata.parameters
        if parameter.name.startswith("gov")
    }
    mismatches: list[str] = []

    assert set(catalog_parameters) == set(v1_parameters)
    for name, parameter in catalog_parameters.items():
        expected = (v1_parameters[name]["economy"], v1_parameters[name]["household"])
        if (parameter.economy, parameter.household) != expected:
            mismatches.append(
                f"{name}: catalog {(parameter.economy, parameter.household)}, "
                f"v1 {expected}"
            )

    assert not mismatches, _report(mismatches)


def test_bracket_schedules_are_nodes_with_the_stored_label_v1_shows(
    country_pair: tuple[ModelMetadata, Any],
) -> None:
    """Every schedule v1 lists is a catalog node; a stored label matches v1's.

    v1 falls back to the name's last part when a schedule has no stored label;
    the catalog stores no label, and the routes generate one.
    """
    from policyengine_core.parameters import ParameterScale

    metadata, v1_country = country_pair
    nodes = {node.name: node for node in metadata.parameter_nodes}
    v1_parameters = v1_country.metadata["parameters"]
    schedules = [
        parameter
        for parameter in v1_country.tax_benefit_system.parameters.get_descendants()
        if isinstance(parameter, ParameterScale) and parameter.name.startswith("gov")
    ]
    mismatches: list[str] = []

    assert schedules
    for schedule in schedules:
        node = nodes.get(schedule.name)
        stored_label = schedule.metadata.get("label")
        if node is None:
            mismatches.append(f"{schedule.name}: not a catalog node")
        elif node.label != stored_label:
            mismatches.append(
                f"{schedule.name}: catalog label {node.label!r}, "
                f"stored label {stored_label!r}"
            )
        elif stored_label is not None and (
            v1_parameters[schedule.name]["label"] != stored_label
        ):
            mismatches.append(
                f"{schedule.name}: catalog label {node.label!r}, "
                f"v1 label {v1_parameters[schedule.name]['label']!r}"
            )

    assert not mismatches, _report(mismatches)
