from policyengine_api.country import COUNTRIES
from tests.fixtures.integration.simulations import (
    TEST_COUNTRY_ID,
    TEST_STATE,
    TEST_YEAR,
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
        result = country.calculate(household_with_axes, {}).household

        # This variable does not function like others; it is a list of member names and is not calculated
        FORBIDDEN_VARIABLES = ["members"]

        # Verify every variable value is expanded across the configured axis.
        for entity_type in result:
            if entity_type == "axes":
                continue
            for entity_id in result[entity_type]:
                for variable_name in result[entity_type][entity_id]:
                    if variable_name in FORBIDDEN_VARIABLES:
                        continue
                    for period in result[entity_type][entity_id][variable_name]:
                        value = result[entity_type][entity_id][variable_name][period]
                        assert isinstance(value, list), (
                            f"Expected an array for {variable_name} on "
                            f"{entity_id} in {period}, got {type(value).__name__}"
                        )
                        assert len(value) == SMALL_AXES_COUNT, (
                            f"Expected {SMALL_AXES_COUNT} values for "
                            f"{variable_name}, got {len(value)}"
                        )

        assert result["people"]["adult"]["age"][TEST_YEAR] == [40] * SMALL_AXES_COUNT
        assert result["people"]["adult"]["employment_income"][TEST_YEAR] == [
            20_000,
            25_000,
            30_000,
            35_000,
            40_000,
        ]
        assert (
            result["households"]["household"]["state_name"][TEST_YEAR]
            == [TEST_STATE] * SMALL_AXES_COUNT
        )
