import pytest
from unittest.mock import Mock, patch, MagicMock
import numpy as np
from policyengine_api.country import COUNTRIES
from policyengine_api.endpoints.household import add_yearly_variables
from tests.fixtures.integration.simulations import (
    TEST_COUNTRY_ID,
    SMALL_AXES_COUNT,
    setup_small_axes_household,
    create_base_household,
    create_small_axes,
)


class TestSimsWithAxes:

    def test__given_any_number_of_axes__sim_returns_valid_arrays(
        self,
    ):  # , patched_add_yearly_variables, patched_countries_get):
        """Integration test with small axes for speed"""
        base_household = create_base_household()
        small_axes_config = create_small_axes()
        household_with_axes = setup_small_axes_household(
            base_household, small_axes_config
        )
        country = COUNTRIES.get(TEST_COUNTRY_ID)
        result = country.calculate(household_with_axes, {})

        # This variable does not function like others; it is a list of member names and is not calculated
        FORBIDDEN_VARIABLES = ["members"]

        # Verify we get array results
        for entity_type in result:
            print("Entity type: ", entity_type)
            if entity_type == "axes":
                continue
            for entity_id in result[entity_type]:
                print("Entity ID: ", entity_id)
                for variable_name in result[entity_type][entity_id]:
                    print("Variable name: ", variable_name)
                    if variable_name in FORBIDDEN_VARIABLES:
                        continue
                    for period in result[entity_type][entity_id][variable_name]:
                        print("Period: ", period)
                        value = result[entity_type][entity_id][variable_name][period]
                        print(f"Value: {value}")
                        if isinstance(value, list):
                            # Assert no Nones
                            assert all(
                                v is not None for v in value
                            ), f"None found in {variable_name} for {entity_id} in {period}"
                            # Assert correct length
                            assert (
                                len(value) == SMALL_AXES_COUNT
                            ), f"Expected {SMALL_AXES_COUNT} values for {variable_name}, got {len(value)}"
