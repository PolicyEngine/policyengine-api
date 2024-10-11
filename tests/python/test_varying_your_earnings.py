from policyengine_api.country import COUNTRIES
from policyengine_api.endpoints.household import add_yearly_variables

# Create two test policies
baseline_policy = {}

reform_policy = {
    "gov.contrib.states.ny.wftc.in_effect": {"2024-01-01.2100-12-31": True}
}

# Create sample household that should be durable across legal changes -
# low-ish income, married, three children
household = {
    "people": {
        "you": {"age": {"2024": 40}, "employment_income": {"2024": 28000}},
        "your partner": {
            "age": {"2024": 40},
            "employment_income": {"2024": 0},
        },
        "your first dependent": {
            "age": {"2024": 10},
            "employment_income": {"2024": 0},
        },
        "your second dependent": {
            "age": {"2024": 10},
            "employment_income": {"2024": 0},
        },
        "your third dependent": {
            "age": {"2024": 10},
            "employment_income": {"2024": 0},
        },
    },
    "families": {
        "your family": {
            "members": [
                "you",
                "your partner",
                "your first dependent",
                "your second dependent",
                "your third dependent",
            ]
        }
    },
    "marital_units": {
        "your marital unit": {"members": ["you", "your partner"]},
        "your first dependent's marital unit": {
            "members": ["your first dependent"],
            "marital_unit_id": {"2024": 1},
        },
        "your second dependent's marital unit": {
            "members": ["your second dependent"],
            "marital_unit_id": {"2024": 2},
        },
        "your third dependent's marital unit": {
            "members": ["your third dependent"],
            "marital_unit_id": {"2024": 3},
        },
    },
    "tax_units": {
        "your tax unit": {
            "members": [
                "you",
                "your partner",
                "your first dependent",
                "your second dependent",
                "your third dependent",
            ]
        }
    },
    "spm_units": {
        "your household": {
            "members": [
                "you",
                "your partner",
                "your first dependent",
                "your second dependent",
                "your third dependent",
            ]
        }
    },
    "households": {
        "your household": {
            "members": [
                "you",
                "your partner",
                "your first dependent",
                "your second dependent",
                "your third dependent",
            ],
            "state_name": {"2024": "NY"},
        }
    },
}


# Testing light reproduction of calculate_full endpoint
def repro_calculate_full(household_json, policy_json):
    country_id = "us"

    household_json = add_yearly_variables(household_json, country_id)
    country = COUNTRIES.get(country_id)
    result = country.calculate(household_json, policy_json)
    return result


# Function to add "axes" entry to household_json
def add_axes(household_json):
    axes = [
        [
            {
                "name": "employment_income",
                "period": "2024",
                "min": 0,
                "max": 200_000,
                "count": 401,
            }
        ]
    ]

    household_json["axes"] = axes

    return household_json


# Begin tests
def test_varying_your_earnings():
    """
    Test the NY CTC policy with varying employment income
    """
    baseline_household = repro_calculate_full(household, baseline_policy)
    print("\nBaseline NY_CTC:")
    print(baseline_household["tax_units"]["your tax unit"]["ny_ctc"]["2024"])

    # For our baseline household, where the WFTC doesn't exist, the NY CTC should be non-zero
    assert (
        baseline_household["tax_units"]["your tax unit"]["ny_ctc"]["2024"] != 0
    )

    reform_household = repro_calculate_full(household, reform_policy)
    print("\nReform NY_CTC:")
    print(reform_household["tax_units"]["your tax unit"]["ny_ctc"]["2024"])

    # For our reform household, when the WFTC is activated, the NY CTC is neutralized, hence $0
    assert (
        int(reform_household["tax_units"]["your tax unit"]["ny_ctc"]["2024"])
        == 0
    )

    household_with_axes = add_axes(household)

    baseline_household_axes = repro_calculate_full(
        household_with_axes, baseline_policy
    )
    print("\nBaseline NY_CTC with axes:")
    print(
        baseline_household_axes["tax_units"]["your tax unit"]["ny_ctc"]["2024"]
    )

    # Our baseline with axes should start taper out, eventually hitting zero
    assert not all(
        int(x) == 0
        for x in baseline_household_axes["tax_units"]["your tax unit"][
            "ny_ctc"
        ]["2024"]
    ), "Error: Array is filled with zeros"

    reform_household_axes = repro_calculate_full(
        household_with_axes, reform_policy
    )
    print("\nReform NY_CTC with axes:")
    print(
        reform_household_axes["tax_units"]["your tax unit"]["ny_ctc"]["2024"]
    )

    # This should be neutralized, hence 401 0's
    assert all(
        int(x) == 0
        for x in reform_household_axes["tax_units"]["your tax unit"]["ny_ctc"][
            "2024"
        ]
    ), "Error: Array is not filled with zeros"
