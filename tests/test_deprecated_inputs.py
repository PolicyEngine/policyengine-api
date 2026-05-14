from policyengine_api.utils.deprecated_inputs import drop_deprecated_inputs


def test_drop_deprecated_inputs_removes_medical_out_of_pocket_expenses():
    household = {
        "people": {
            "you": {
                "age": {"2025": 30},
                "medical_out_of_pocket_expenses": {"2025": 100},
                "employment_income": {"2025": 10_000},
                "medicaid": {"2025": None},
            }
        }
    }

    result = drop_deprecated_inputs(household)

    cleaned_person = result.household["people"]["you"]
    assert "medical_out_of_pocket_expenses" not in cleaned_person
    assert cleaned_person["medicaid"] == {"2025": None}
    assert household["people"]["you"]["medical_out_of_pocket_expenses"] == {
        "2025": 100
    }
    assert len(result.warnings) == 1
    assert result.warnings[0].variable == "medical_out_of_pocket_expenses"
    assert "other_medical_expenses" in result.warnings[0].message


def test_drop_deprecated_inputs_removes_axes_for_removed_variables():
    household = {
        "people": {"you": {"age": {"2025": 30}, "medicaid": {"2025": None}}},
        "axes": [
            [
                {"name": "medical_out_of_pocket_expenses", "min": 0, "max": 100},
                {"name": "employment_income", "min": 0, "max": 1_000},
            ]
        ],
    }

    result = drop_deprecated_inputs(household)

    assert result.household["axes"] == [
        [{"name": "employment_income", "min": 0, "max": 1_000}]
    ]
    assert len(result.warnings) == 1
    assert result.warnings[0].entity_plural == "axes"
    assert "axes[0][0].name" in result.warnings[0].message
