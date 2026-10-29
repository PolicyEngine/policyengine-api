"""The messages and error entries for household axes policyengine-core cannot expand.

Which shapes policyengine-core expands is checked against policyengine-core itself
in tests/unit/routes/test_calculate_axis_validation.py.
"""

import pytest

from policyengine_api.utils.axis_validation import InvalidAxisInput, find_invalid_axes
from policyengine_api.utils.deprecated_inputs import drop_deprecated_inputs
from policyengine_api.utils.input_validation import (
    UnrecognizedInput,
    find_invalid_inputs,
    format_invalid_inputs_message,
)

METADATA = {
    "variables": {"employment_income": {"entity": "person"}},
    "entities": {"person": {"plural": "people", "roles": {}}},
    "parameters": {},
}


def income_axis(**fields: object) -> dict:
    """Return a complete axis over employment income, with ``fields`` replaced."""
    return {
        "name": "employment_income",
        "period": "2026",
        "min": 0,
        "max": 100_000,
        "count": 3,
        **fields,
    }


@pytest.mark.parametrize("axes", [None, [], {}, "", 0, False])
def test_axes_that_policyengine_core_ignores_are_not_checked(axes: object) -> None:
    assert find_invalid_axes(axes) == []


def test_a_field_error_names_the_axis_its_variable_and_the_field() -> None:
    axis = income_axis()
    del axis["max"]

    [error] = find_invalid_axes([[axis]])

    assert error.to_dict() == {
        "type": "household_axis",
        "name": "max",
        "path": "household.axes[0][0].max",
        "message": (
            "Household axis `household.axes[0][0]` (`employment_income`) needs "
            "`max` to be a finite number, but it is missing."
        ),
    }


def test_a_structure_error_names_the_value_at_fault() -> None:
    [error] = find_invalid_axes([[income_axis()], []])

    assert error.to_dict() == {
        "type": "household_axis",
        "name": "axes",
        "path": "household.axes[1]",
        "message": (
            "`household.axes[1]` must be a non-empty list of axes, "
            "but it is an empty list."
        ),
    }


def test_every_unusable_field_of_an_axis_is_reported_in_field_order() -> None:
    axis = {"name": 5, "count": "3", "period": "January", "index": 1.5}

    errors = find_invalid_axes([[axis]])

    assert [(error.field, error.received) for error in errors] == [
        ("name", "5"),
        ("count", '"3"'),
        ("min", "missing"),
        ("max", "missing"),
        ("period", '"January"'),
        ("index", "1.5"),
    ]
    assert all(error.variable_name is None for error in errors)


@pytest.mark.parametrize(
    ("value", "description"),
    [
        (None, "null"),
        (float("nan"), "NaN"),
        ("x" * 41, "a string"),
        ([1], "a list"),
        ({"value": 1}, "an object"),
    ],
)
def test_received_values_are_described_as_json(value: object, description: str):
    [error] = find_invalid_axes([[income_axis(max=value)]])

    assert error.received == description


def test_axes_that_are_a_boolean_are_described_as_json() -> None:
    [error] = find_invalid_axes(axes=True)

    assert error.message == (
        "`household.axes` must be a list of axis groups, but it is true."
    )


@pytest.mark.parametrize("period", [None, "", 0])
def test_a_grid_reads_a_falsy_period_as_the_default_period(period: object) -> None:
    grid = [[income_axis(period=period)], [income_axis(count=2)]]

    assert find_invalid_axes(grid) == []
    assert [error.field for error in find_invalid_axes([grid[0]])] == ["period"]


def test_axis_problems_precede_unrecognized_names_in_one_message() -> None:
    household = {
        "people": {"you": {"employment_incomee": {"2026": 1}}},
        "axes": [[income_axis(count=None)]],
    }

    errors = find_invalid_inputs(household, {}, METADATA)

    assert [type(error) for error in errors] == [InvalidAxisInput, UnrecognizedInput]
    assert format_invalid_inputs_message(errors) == (
        "Invalid calculate input(s): Household axis `household.axes[0][0]` "
        "(`employment_income`) needs `count` to be an integer of at least 1, "
        "written without a decimal point, but it is null.; Unrecognized household "
        "variable `employment_incomee` at `household.people.you.employment_incomee`."
    )


def test_unrecognized_names_alone_keep_their_message_wording() -> None:
    household = {"axes": [[income_axis(name="employment_incomee")]]}

    errors = find_invalid_inputs(household, {}, METADATA)

    assert format_invalid_inputs_message(errors) == (
        "Unrecognized calculate input(s): Unrecognized household axis variable "
        "`employment_incomee` at `household.axes[0][0].name`."
    )


def test_an_axis_name_that_is_not_a_string_is_reported_once() -> None:
    household = {"axes": [[income_axis(name=["employment_income"])]]}

    errors = find_invalid_inputs(household, {}, METADATA)

    assert [error.to_dict()["path"] for error in errors] == [
        "household.axes[0][0].name"
    ]
    assert isinstance(errors[0], InvalidAxisInput)


def test_dropping_deprecated_axes_keeps_an_axis_named_by_a_list() -> None:
    axes = [[income_axis(name=["employment_income"])]]

    result = drop_deprecated_inputs({"axes": axes})

    assert result.household == {"axes": axes}
    assert result.warnings == []
