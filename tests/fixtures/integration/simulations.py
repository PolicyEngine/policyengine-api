"""
Test fixtures and constants for axes calculation tests
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from policyengine_api.endpoints.household import add_yearly_variables

STANDARD_AXES_COUNT = 401  # Not formally defined anywhere, but this value is used throughout the API
SMALL_AXES_COUNT = 5
TEST_YEAR = "2025"
TEST_STATE = "NY"
TEST_COUNTRY_ID = "us"

BASE_HOUSEHOLD = {
    "people": {
        "adult": {
            "age": {TEST_YEAR: 40},
            "employment_income": {TEST_YEAR: 30000},
        },
    },
    "tax_units": {"unit": {"members": ["adult"]}},
    "households": {
        "household": {
            "members": ["adult"],
            "state_name": {TEST_YEAR: TEST_STATE},
        }
    },
}

SMALL_AXES_CONFIG = [
    [
        {
            "name": "employment_income",
            "period": TEST_YEAR,
            "min": 20000,
            "max": 40000,
            "count": SMALL_AXES_COUNT,
        }
    ]
]


# Pytest fixtures
def create_base_household():
    """Returns a copy of the base household configuration"""
    import copy

    return copy.deepcopy(BASE_HOUSEHOLD)


def create_small_axes():
    """Returns the small axes configuration for faster tests"""
    import copy

    return copy.deepcopy(SMALL_AXES_CONFIG)


def create_household_with_axes(base_household, axes_config):
    """Helper function to add axes to a household"""
    import copy

    household = copy.deepcopy(base_household)
    household["axes"] = axes_config
    return household


def setup_small_axes_household(base_household, small_axes_config):
    """Fixture to setup a household with small axes for testing"""
    household_with_axes = create_household_with_axes(
        base_household, small_axes_config
    )
    household_with_axes = add_yearly_variables(
        household_with_axes, TEST_COUNTRY_ID
    )
    return household_with_axes
