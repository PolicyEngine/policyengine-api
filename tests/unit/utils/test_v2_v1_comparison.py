import pytest
from policyengine_api.utils.v2_v1_comparison import (
    V2V1Comparison,
    compute_difference,
)
from tests.fixtures.utils.v2_v1_comparison import (
    valid_v2_v1_comparison,
    invalid_v2_v1_comparison,
)


class TestV2V1Comparison:

    def test__given_valid_inputs__returns_schema(self):

        # When: Creating an instance of V2V1Comparison
        comparison_instance = V2V1Comparison(**valid_v2_v1_comparison)

        # Then: It should return a valid schema
        assert (
            comparison_instance.country_id
            == valid_v2_v1_comparison["country_id"]
        )
        assert comparison_instance.region == valid_v2_v1_comparison["region"]
        assert (
            comparison_instance.reform_policy
            == valid_v2_v1_comparison["reform_policy"]
        )
        assert (
            comparison_instance.baseline_policy
            == valid_v2_v1_comparison["baseline_policy"]
        )
        assert (
            comparison_instance.reform_policy_id
            == valid_v2_v1_comparison["reform_policy_id"]
        )
        assert (
            comparison_instance.baseline_policy_id
            == valid_v2_v1_comparison["baseline_policy_id"]
        )
        assert (
            comparison_instance.time_period
            == valid_v2_v1_comparison["time_period"]
        )
        assert comparison_instance.dataset == valid_v2_v1_comparison["dataset"]
        assert comparison_instance.v2_id == valid_v2_v1_comparison["v2_id"]
        assert (
            comparison_instance.v2_error == valid_v2_v1_comparison["v2_error"]
        )
        assert (
            comparison_instance.v1_impact
            == valid_v2_v1_comparison["v1_impact"]
        )
        assert (
            comparison_instance.v2_impact
            == valid_v2_v1_comparison["v2_impact"]
        )
        assert (
            comparison_instance.v1_v2_diff
            == valid_v2_v1_comparison["v1_v2_diff"]
        )
        assert comparison_instance.message == valid_v2_v1_comparison["message"]

    def test__given_invalid_inputs__raises_validation_error(self):

        # When: Creating an instance of V2V1Comparison with invalid inputs
        with pytest.raises(
            Exception, match=r"validation errors? for V2V1Comparison"
        ):
            V2V1Comparison(**invalid_v2_v1_comparison)


class TestComputeDifference:

    def test__given_identical_numbers__returns_0(self):
        # Given: Two identical numbers
        x = 10
        y = 10

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return 0
        assert result is None

    def test__given_different_numbers__returns_difference(self):
        # Given: Two different numbers
        x = 10
        y = 5

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return the difference
        assert result == 5

    def test__given_identical_strings__returns_none(self):
        # Given: Two identical strings
        x = "hello"
        y = "hello"

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return None
        assert result is None

    def test__given_different_strings__returns_strings(self):
        # Given: Two different strings
        x = "hello"
        y = "world"

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return a formatted string
        assert result == "v1: hello, v2: world"

    def test__given_identical_dicts__returns_none(self):
        # Given: Two identical dictionaries
        x = {"key": "value"}
        y = {"key": "value"}

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return None
        assert result is None

    def test__given_identical_dicts_with_different_order__returns_none(self):
        # Given: Two identical dictionaries with different key order
        x = {"key1": "value1", "key2": "value2"}
        y = {"key2": "value2", "key1": "value1"}

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return None
        assert result is None

    def test__given_identical_dicts_with_numerical_keys__returns_none(self):
        # Given: Two identical dictionaries with numerical keys
        x = {1: "value1", 2: "value2"}
        y = {1: "value1", 2: "value2"}

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return None
        assert result is None

    def test__given_identical_dicts_with_numerical_keys_of_different_types_and_order__returns_none(
        self,
    ):
        # Given: Two identical dictionaries with numerical keys of different types and order
        x = {1: "value1", 2: "value2"}
        y = {"2": "value2", "1": "value1"}

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return None
        assert result is None

    def test__given_different_dicts__returns_dict_difference(self):
        # Given: Two different dictionaries
        x = {"key1": "value1", "key2": "value2"}
        y = {"key1": "value1", "key3": "value3"}

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return a dictionary with differences
        assert result == {
            "key2": "v1: value2, v2: <missing>",
            "key3": "v1: <missing>, v2: value3",
        }

    def test__given_identical_bools__returns_none(self):
        # Given: Two identical booleans
        x = True
        y = True

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return None
        assert result is None

    def test__given_different_bools__returns_bools(self):
        # Given: Two different booleans
        x = True
        y = False

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return a formatted string
        assert result == "v1: True, v2: False"

    def test__given_nan_values__returns_nan_string(self):
        # Given: Two NaN values
        x = float("nan")
        y = float("nan")

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return None
        assert result is None

    def test__given_nan_and_number__returns_nan_string(self):
        # Given: A NaN value and a number
        x = float("nan")
        y = 10

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return a formatted string
        assert result == "v1: NaN, v2: 10.0"

    def test__given_none_and_int__returns_none_string(self):
        # Given: A None value and an integer
        x = None
        y = 10

        # When: Computing the difference
        result = compute_difference(x, y)

        # Then: It should return a formatted string
        assert result == "v1: None, v2: 10"
