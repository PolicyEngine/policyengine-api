from policyengine_api.utils.input_validation import find_unrecognized_inputs


METADATA = {
    "variables": {
        "age": {"entity": "person"},
        "employment_income": {"entity": "person"},
        "snap": {"entity": "spm_unit"},
    },
    "entities": {
        "person": {
            "plural": "people",
            "roles": {},
        },
        "spm_unit": {
            "plural": "spm_units",
            "roles": {
                "member": {
                    "plural": "members",
                },
            },
        },
    },
    "parameters": {
        "gov.irs.income.exemption.amount": {},
    },
}


def test__find_unrecognized_inputs__accepts_known_household_and_policy_inputs():
    household = {
        "people": {"you": {"age": {"2025": 49}}},
        "spm_units": {
            "spm_unit": {
                "members": ["you"],
                "snap": {"2025": None},
            }
        },
        "axes": [[{"name": "employment_income", "count": 2}]],
    }
    policy = {"gov.irs.income.exemption.amount": {"2025-01-01.2025-12-31": 100}}

    errors = find_unrecognized_inputs(household, policy, METADATA)

    assert errors == []


def test__find_unrecognized_inputs__reports_unknown_entity_variable_axis_and_policy():
    household = {
        "person": {"you": {"age": {"2025": 49}}},
        "people": {"you": {"age": {"2025": 49}, "snap": {"2025": None}}},
        "axes": [[{"name": "employmnt_income", "count": 2}]],
    }
    policy = {"gov.irs.income.exemption.amunt": {"2025-01-01.2025-12-31": 100}}

    errors = find_unrecognized_inputs(household, policy, METADATA)

    assert [error.input_type for error in errors] == [
        "household_entity",
        "household_variable_wrong_entity",
        "household_axis_variable",
        "policy_parameter",
    ]
    assert [error.path for error in errors] == [
        "household.person",
        "household.people.you.snap",
        "household.axes[0][0].name",
        "policy.gov.irs.income.exemption.amunt",
    ]
