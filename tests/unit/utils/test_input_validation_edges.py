"""Pin every household-input finding, in order, and JSON-safe metadata values."""

from __future__ import annotations

import math

import numpy as np
import pytest

from policyengine_api.utils.input_validation import (
    UnrecognizedInput,
    find_unrecognized_household_inputs,
)
from policyengine_api.utils.json import get_safe_json

METADATA = {
    "variables": {
        "age": {"entity": "person"},
        "snap": {"entity": "spm_unit"},
        "region": {"entity": "region_without_plural"},
        "state_code": {"entity": "unknown_entity"},
    },
    "entities": {
        "person": {"plural": "people", "roles": {}},
        "spm_unit": {
            "plural": "spm_units",
            "roles": {"member": {"plural": "members"}, "head": {}},
        },
        "region_without_plural": {},
    },
}


@pytest.mark.parametrize("household", [None, [], "household"])
def test_non_object_households_report_nothing(household: object) -> None:
    assert find_unrecognized_household_inputs(household, METADATA) == []


def test_household_findings_are_reported_in_document_order() -> None:
    household = {
        "people": {
            "you": {
                "age": {"2026": 40},
                "snap": {"2026": None},
                "agee": {"2026": 1},
                "region": {"2026": "x"},
                "state_code": {"2026": "CA"},
            },
            "partner": ["not", "an", "object"],
        },
        "spm_units": {"unit": {"members": ["you"], "snapp": {"2026": 0}}},
        "tax_units": {"unit": {}},
        "households": ["not an object"],
        "axes": [{"name": "agge"}, [{"name": "age"}, {"name": "snapp"}]],
    }

    findings = find_unrecognized_household_inputs(household, METADATA)

    assert findings == [
        UnrecognizedInput(
            input_type="household_variable_wrong_entity",
            name="snap",
            path="household.people.you.snap",
            expected_entity_plural="spm_units",
            actual_entity_plural="people",
        ),
        UnrecognizedInput(
            input_type="household_variable",
            name="agee",
            path="household.people.you.agee",
        ),
        UnrecognizedInput(
            input_type="household_variable",
            name="snapp",
            path="household.spm_units.unit.snapp",
        ),
        UnrecognizedInput(
            input_type="household_entity",
            name="tax_units",
            path="household.tax_units",
        ),
        UnrecognizedInput(
            input_type="household_entity",
            name="households",
            path="household.households",
        ),
        UnrecognizedInput(
            input_type="household_axis_variable",
            name="agge",
            path="household.axes[0].name",
        ),
        UnrecognizedInput(
            input_type="household_axis_variable",
            name="snapp",
            path="household.axes[1][1].name",
        ),
    ]


def test_known_entity_groups_that_are_not_objects_are_skipped() -> None:
    assert find_unrecognized_household_inputs({"people": ["you"]}, METADATA) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (math.inf, "Infinity"),
        (-math.inf, "-Infinity"),
        (np.inf, "Infinity"),
        (-np.inf, "-Infinity"),
        (3, 3),
        (2.5, 2.5),
        (True, True),
        ("text", "text"),
        ({"a": [1, -math.inf, None]}, {"a": [1, "-Infinity", None]}),
        (None, None),
        ((1, 2), None),
        (object, None),
    ],
)
def test_safe_json_writes_infinities_as_strings(
    value: object,
    expected: object,
) -> None:
    assert get_safe_json(value) == expected
