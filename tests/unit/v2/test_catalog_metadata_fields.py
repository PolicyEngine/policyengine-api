"""Catalog format 2: the metadata v3 reads, taken from .py's public records."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from policyengine_api.data.v2.catalog.extraction import (
    CatalogExtractionError,
    extract_catalog,
)
from policyengine_api.data.v2.catalog.records import (
    CATALOG_FORMAT,
    EntityRecord,
    EnumValueRecord,
    NormalizedCatalog,
)
from tests.fixtures.v2_catalog import (
    POLICYENGINE_VERSION,
    bundle,
    installed_version,
    normalized_catalog,
    region_references,
    source_models,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _extract(models: dict[str, SimpleNamespace]) -> NormalizedCatalog:
    return extract_catalog(
        bundle=bundle(),
        policyengine_version=POLICYENGINE_VERSION,
        models=models,
        installed_version=installed_version,
        region_references=region_references(),
    )


def _add_variable(model: SimpleNamespace, **fields: object) -> None:
    variable = SimpleNamespace(
        label=None,
        entity="person",
        description=None,
        data_type=float,
        possible_values=None,
        default_value=0.0,
        adds=None,
        subtracts=None,
        is_input_variable=False,
        hidden_input=False,
        module_name=None,
        adds_parameter_path=None,
        subtracts_parameter_path=None,
        enum_values=None,
    )
    for name, value in fields.items():
        setattr(variable, name, value)
    model.variables.append(variable)
    model.variables_by_name[variable.name] = variable


def _add_parameter(model: SimpleNamespace, name: str, *, value: object) -> None:
    parameter = SimpleNamespace(
        name=name,
        label=None,
        description=None,
        data_type=type(value),
        unit=None,
        economy=True,
        household=True,
        parameter_values=[
            SimpleNamespace(
                value=value,
                start_date=datetime(2025, 1, 1, tzinfo=UTC),
                end_date=None,
            )
        ],
    )
    model.parameters.append(parameter)
    model.parameters_by_name[name] = parameter


def _add_parameter_node(model: SimpleNamespace, name: str, label: str | None) -> None:
    node = SimpleNamespace(name=name, label=label, description=None)
    model.parameter_nodes.append(node)
    model.parameter_nodes_by_name[name] = node


def test_catalog_format_2_publishes_entities_and_basic_inputs() -> None:
    catalog = normalized_catalog()

    for country_id in ("us", "uk"):
        model_version = catalog.country(country_id).model_version
        assert model_version.catalog_format == CATALOG_FORMAT == 2
        assert model_version.entities == (
            EntityRecord(key="person", plural="people", is_person=True),
            EntityRecord(key="household", plural="households", is_person=False),
        )
        assert model_version.basic_inputs == ("employment_income",)


def test_variables_carry_input_flags_module_and_unset_parts() -> None:
    variable = normalized_catalog().country("us").variables[0]

    assert variable.name == "employment_income"
    assert variable.is_input_variable is True
    assert variable.hidden_input is False
    assert variable.module_name == "household.income.employment_income"
    assert variable.adds_parameter_path is None
    assert variable.subtracts_parameter_path is None
    assert variable.enum_values is None


def test_enum_values_keep_their_declared_labels_in_order() -> None:
    models = source_models()
    _add_variable(
        models["us"],
        name="filing_status",
        data_type="Enum",
        possible_values=["SINGLE", "JOINT", "EXEMPT"],
        default_value="SINGLE",
        is_input_variable=True,
        enum_values=[
            SimpleNamespace(value="SINGLE", label="Single"),
            SimpleNamespace(value="JOINT", label=2),
            SimpleNamespace(value="EXEMPT", label=None),
        ],
    )

    variables = {
        variable.name: variable for variable in _extract(models).country("us").variables
    }

    assert variables["filing_status"].enum_values == (
        EnumValueRecord(value="SINGLE", label="Single"),
        EnumValueRecord(value="JOINT", label=2),
        EnumValueRecord(value="EXEMPT", label=None),
    )
    assert isinstance(variables["filing_status"].enum_values[1].label, int)


def test_parameter_named_parts_record_the_parameter_path_beside_the_list() -> None:
    models = source_models()
    _add_parameter(
        models["us"],
        "gov.example.countable_income",
        value=["employment_income"],
    )
    _add_parameter(models["us"], "gov.example.deductions", value=["employment_income"])
    _add_variable(
        models["us"],
        name="countable_income",
        adds=["employment_income"],
        subtracts=["employment_income"],
        adds_parameter_path="gov.example.countable_income",
        subtracts_parameter_path="gov.example.deductions",
    )

    variables = {
        variable.name: variable for variable in _extract(models).country("us").variables
    }

    countable_income = variables["countable_income"]
    assert countable_income.adds_parameter_path == "gov.example.countable_income"
    assert countable_income.subtracts_parameter_path == "gov.example.deductions"
    assert countable_income.adds == ["employment_income"]
    assert countable_income.subtracts == ["employment_income"]


def test_parameters_carry_their_economy_and_household_flags() -> None:
    parameter = normalized_catalog().country("us").parameters[0]

    assert parameter.name == "gov.example.rate"
    assert (parameter.economy, parameter.household) == (True, False)


def test_bracket_schedules_are_stored_as_nodes_with_their_stored_label() -> None:
    models = source_models()
    _add_parameter_node(models["uk"], "gov.example.rates", "Example rates")
    _add_parameter_node(models["uk"], "gov.example.rates[0]", None)
    _add_parameter_node(models["uk"], "gov.example.thresholds", None)
    _add_parameter_node(models["uk"], "gov.example.thresholds[0]", None)
    _add_parameter(models["uk"], "gov.example.rates[0].rate", value=0.2)
    _add_parameter(models["uk"], "gov.example.thresholds[0].threshold", value=0)

    nodes = {node.name: node for node in _extract(models).country("uk").parameter_nodes}

    assert nodes["gov.example.rates"].label == "Example rates"
    assert nodes["gov.example.thresholds"].label is None
    assert "gov.example.rates[0]" in nodes


def _remove_entities(models: dict[str, SimpleNamespace]) -> None:
    del models["us"].entities


def _make_entity_flag_text(models: dict[str, SimpleNamespace]) -> None:
    models["us"].entities[0].is_person = "yes"


def _remove_person_entity(models: dict[str, SimpleNamespace]) -> None:
    models["us"].entities = models["us"].entities[1:]


def _repeat_entity_key(models: dict[str, SimpleNamespace]) -> None:
    models["us"].entities.append(
        SimpleNamespace(key="household", plural="homes", is_person=False)
    )


def _remove_basic_inputs(models: dict[str, SimpleNamespace]) -> None:
    del models["us"].basic_inputs


def _make_entities_null(models: dict[str, SimpleNamespace]) -> None:
    models["us"].entities = None


def _make_basic_inputs_text(models: dict[str, SimpleNamespace]) -> None:
    models["us"].basic_inputs = "employment_income"


def _remove_variable_enum_values(models: dict[str, SimpleNamespace]) -> None:
    del models["us"].variables[0].enum_values


def _make_enum_label_nan(models: dict[str, SimpleNamespace]) -> None:
    variable = models["us"].variables[0]
    variable.possible_values = ["SINGLE"]
    variable.enum_values = [SimpleNamespace(value="SINGLE", label=float("nan"))]


def _name_unknown_basic_input(models: dict[str, SimpleNamespace]) -> None:
    models["us"].basic_inputs = ["employment_income", "unpublished_input"]


def _make_input_flag_text(models: dict[str, SimpleNamespace]) -> None:
    models["us"].variables[0].is_input_variable = "true"


def _make_hidden_flag_number(models: dict[str, SimpleNamespace]) -> None:
    models["us"].variables[0].hidden_input = 0


def _name_unknown_adds_parameter(models: dict[str, SimpleNamespace]) -> None:
    models["us"].variables[0].adds_parameter_path = "gov.example.missing"


def _name_unknown_subtracts_parameter(models: dict[str, SimpleNamespace]) -> None:
    models["us"].variables[0].subtracts_parameter_path = "gov.example.missing"


def _mismatch_enum_values(models: dict[str, SimpleNamespace]) -> None:
    variable = models["us"].variables[0]
    variable.possible_values = ["SINGLE", "JOINT"]
    variable.enum_values = [SimpleNamespace(value="SINGLE", label="Single")]


def _give_enum_labels_without_values(models: dict[str, SimpleNamespace]) -> None:
    models["us"].variables[0].enum_values = [
        SimpleNamespace(value="SINGLE", label="Single")
    ]


def _make_enum_label_an_object(models: dict[str, SimpleNamespace]) -> None:
    variable = models["us"].variables[0]
    variable.possible_values = ["SINGLE"]
    variable.enum_values = [SimpleNamespace(value="SINGLE", label={"text": "Single"})]


def _make_economy_flag_missing(models: dict[str, SimpleNamespace]) -> None:
    del models["us"].parameters[0].economy


def _make_economy_flag_null(models: dict[str, SimpleNamespace]) -> None:
    models["us"].parameters[0].economy = None


def _make_household_flag_text(models: dict[str, SimpleNamespace]) -> None:
    models["us"].parameters[0].household = "false"


@pytest.mark.parametrize(
    ("break_models", "message"),
    [
        (
            _remove_entities,
            "^the installed PolicyEngine.py does not publish catalog format 2's "
            "fields for us: model version entities$",
        ),
        (_make_entities_null, "^us public model entities must be a sequence$"),
        (_make_entity_flag_text, "^us entity person is_person must be a boolean$"),
        (
            _remove_person_entity,
            "^us public model must have exactly one person entity$",
        ),
        (_repeat_entity_key, "^us entity key 'household' is repeated$"),
        (
            _remove_basic_inputs,
            "^the installed PolicyEngine.py does not publish catalog format 2's "
            "fields for us: model version basic_inputs$",
        ),
        (
            _make_basic_inputs_text,
            "^us public model basic_inputs must be a sequence$",
        ),
        (
            _remove_variable_enum_values,
            "^the installed PolicyEngine.py does not publish catalog format 2's "
            "fields for us: variable enum_values$",
        ),
        (
            _make_enum_label_nan,
            "^variable employment_income enum label for SINGLE is not "
            "JSON-compatible: NaN is not JSON-compatible$",
        ),
        (
            _name_unknown_basic_input,
            "^us basic input 'unpublished_input' is not a published variable$",
        ),
        (
            _make_input_flag_text,
            "^variable employment_income is_input_variable must be a boolean or null$",
        ),
        (
            _make_hidden_flag_number,
            "^variable employment_income hidden_input must be a boolean or null$",
        ),
        (
            _name_unknown_adds_parameter,
            "^variable employment_income adds_parameter_path 'gov.example.missing' "
            "is not a published parameter$",
        ),
        (
            _name_unknown_subtracts_parameter,
            "^variable employment_income subtracts_parameter_path "
            "'gov.example.missing' is not a published parameter$",
        ),
        (
            _mismatch_enum_values,
            "^variable employment_income enum values do not match its possible values$",
        ),
        (
            _give_enum_labels_without_values,
            "^variable employment_income enum values do not match its possible values$",
        ),
        (
            _make_enum_label_an_object,
            "^variable employment_income enum label for SINGLE must be a JSON scalar$",
        ),
        (
            _make_economy_flag_missing,
            "^the installed PolicyEngine.py does not publish catalog format 2's "
            "fields for us: parameter economy$",
        ),
        (
            _make_economy_flag_null,
            "^parameter gov.example.rate economy must be a boolean$",
        ),
        (
            _make_household_flag_text,
            "^parameter gov.example.rate household must be a boolean$",
        ),
    ],
)
def test_inconsistent_format_2_metadata_fails_with_a_specific_message(
    break_models: Callable[[dict[str, SimpleNamespace]], None],
    message: str,
) -> None:
    models = source_models()
    break_models(models)

    with pytest.raises(CatalogExtractionError, match=message):
        _extract(models)


def test_a_release_without_format_2_fields_fails_naming_each_missing_field() -> None:
    """An older PolicyEngine.py fails before any record is checked, naming what lacks.

    PolicyEngine.py 6.7.5, for example, publishes none of these fields.
    """
    models = source_models()
    model = models["us"]
    del model.entities, model.basic_inputs
    for variable in model.variables:
        for field_name in (
            "is_input_variable",
            "hidden_input",
            "module_name",
            "adds_parameter_path",
            "subtracts_parameter_path",
            "enum_values",
        ):
            delattr(variable, field_name)
    for parameter in model.parameters:
        del parameter.economy, parameter.household

    with pytest.raises(
        CatalogExtractionError,
        match=r"^the installed PolicyEngine.py does not publish catalog format 2's "
        r"fields for us: model version entities, basic_inputs; variable "
        r"is_input_variable, hidden_input, module_name, adds_parameter_path, "
        r"subtracts_parameter_path, enum_values; parameter economy, household$",
    ):
        _extract(models)


def test_an_empty_basic_input_list_is_stored_empty() -> None:
    models = source_models()
    models["us"].basic_inputs = []

    assert _extract(models).country("us").model_version.basic_inputs == ()
