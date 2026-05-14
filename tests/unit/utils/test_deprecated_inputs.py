"""Unit tests for the deprecated-input warn-and-drop helper.

`drop_deprecated_inputs` returns a household copy with removed/renamed
model variables stripped before validation so partners who still pass
them get a structured warning + working response instead of a
`VariableNotFoundError` HTTP 500 from the engine.
"""

import copy

from policyengine_api.utils.deprecated_inputs import (
    DEPRECATED_VARIABLES,
    DeprecatedInputsResult,
    DeprecatedVariableWarning,
    drop_deprecated_inputs,
)


class TestDropDeprecatedInputs:
    def test__deprecated_variable__is_dropped_with_warning(self):
        household = {
            "people": {
                "you": {
                    "age": {"2025": 49},
                    "medical_out_of_pocket_expenses": {"2025": 0},
                }
            }
        }
        original = copy.deepcopy(household)

        result = drop_deprecated_inputs(household)
        cleaned = result.household
        warnings = result.warnings

        assert "medical_out_of_pocket_expenses" not in cleaned["people"]["you"]
        assert household == original
        assert cleaned["people"]["you"]["age"] == {"2025": 49}
        assert len(warnings) == 1
        assert isinstance(result, DeprecatedInputsResult)
        assert isinstance(warnings[0], DeprecatedVariableWarning)
        assert warnings[0].variable == "medical_out_of_pocket_expenses"
        assert warnings[0].entity_plural == "people"
        assert warnings[0].entity_id == "you"
        assert "other_medical_expenses" in warnings[0].hint

    def test__no_deprecated_variables__returns_empty(self):
        household = {
            "people": {"you": {"age": {"2025": 49}}},
            "households": {"household": {"members": ["you"]}},
        }
        original = copy.deepcopy(household)

        result = drop_deprecated_inputs(household)

        assert result.warnings == []
        assert result.household == household
        assert result.household is not household
        assert household == original

    def test__deprecated_variable_on_multiple_people__warns_each(self):
        household = {
            "people": {
                "you": {
                    "medical_out_of_pocket_expenses": {"2025": 100},
                },
                "spouse": {
                    "medical_out_of_pocket_expenses": {"2025": 200},
                },
            }
        }
        original = copy.deepcopy(household)

        result = drop_deprecated_inputs(household)
        warnings = result.warnings

        assert len(warnings) == 2
        ids = {w.entity_id for w in warnings}
        assert ids == {"you", "spouse"}
        assert result.household["people"]["you"] == {}
        assert result.household["people"]["spouse"] == {}
        assert household == original

    def test__list_valued_entity_group__is_skipped_safely(self):
        # `axes` is a list at the household level, not an entity dict.
        # The helper must skip it without raising.
        household = {
            "people": {"you": {"age": {"2025": 49}}},
            "axes": [[{"name": "employment_income", "count": 5}]],
        }
        original = copy.deepcopy(household)

        result = drop_deprecated_inputs(household)

        assert result.warnings == []
        assert result.household["axes"] == [[{"name": "employment_income", "count": 5}]]
        assert household == original

    def test__deprecated_axis_name__is_dropped_with_warning(self):
        household = {
            "people": {"you": {"age": {"2025": 49}}},
            "axes": [
                [
                    {
                        "name": "medical_out_of_pocket_expenses",
                        "period": "2025",
                        "min": 0,
                        "max": 100,
                        "count": 2,
                    },
                    {
                        "name": "employment_income",
                        "period": "2025",
                        "min": 0,
                        "max": 100,
                        "count": 2,
                    },
                ]
            ],
        }
        original = copy.deepcopy(household)

        result = drop_deprecated_inputs(household)
        warnings = result.warnings

        assert result.household["axes"] == [
            [
                {
                    "name": "employment_income",
                    "period": "2025",
                    "min": 0,
                    "max": 100,
                    "count": 2,
                }
            ]
        ]
        assert len(warnings) == 1
        assert warnings[0].entity_plural == "axes"
        assert warnings[0].entity_id == "0][0"
        assert "axes[0][0].name" in warnings[0].message
        assert household == original

    def test__only_deprecated_axis_names__removes_axes_key(self):
        household = {
            "people": {"you": {"age": {"2025": 49}}},
            "axes": [
                [
                    {
                        "name": "medical_out_of_pocket_expenses",
                        "period": "2025",
                        "min": 0,
                        "max": 100,
                        "count": 2,
                    }
                ]
            ],
        }
        original = copy.deepcopy(household)

        result = drop_deprecated_inputs(household)

        assert "axes" not in result.household
        assert len(result.warnings) == 1
        assert household == original

    def test__list_valued_variable__is_not_misinterpreted(self):
        # `members` is a list-valued slot on entity groups; the helper must
        # not try to mutate it.
        household = {
            "spm_units": {
                "spm_unit": {
                    "members": ["you"],
                    "snap": {"2025": None},
                }
            }
        }
        original = copy.deepcopy(household)

        result = drop_deprecated_inputs(household)

        assert result.warnings == []
        assert result.household["spm_units"]["spm_unit"]["members"] == ["you"]
        assert household == original

    def test__warning_message_includes_variable_entity_and_hint(self):
        warning = DeprecatedVariableWarning(
            variable="medical_out_of_pocket_expenses",
            entity_plural="people",
            entity_id="you",
            hint=DEPRECATED_VARIABLES["medical_out_of_pocket_expenses"],
        )

        msg = warning.message

        assert "medical_out_of_pocket_expenses" in msg
        assert "people/you" in msg
        assert "other_medical_expenses" in msg
        assert "deprecated" in msg.lower()
