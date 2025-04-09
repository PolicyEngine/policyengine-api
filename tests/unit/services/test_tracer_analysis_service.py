import pytest

from policyengine_api.services.tracer_analysis_service import (
    TracerAnalysisService,
)
import logging

from tests.fixtures.services.tracer_analysis_service import *


logger = logging.getLogger(__name__)
test_service = TracerAnalysisService()


def test_tracer_output_for_int_input_variable():
    # Given: A tracer output with various income types
    # and a target variable that is an integer (invalid format)
    invalid_target_variable_incorrect_type = 500

    # When: Parsing the tracer output with an invalid target variable
    result = test_service._parse_tracer_output(
        valid_tracer_output, invalid_target_variable_incorrect_type
    )

    # Then: It should return an empty list
    expected_output = empty_tracer
    assert result == expected_output


def test_tracer_output_for_dict_input_tracer():
    # Given: A tracer output with various income types but is in invalid format (dict instead of list of string)
    # and a valid target variable present in the tracer
    valid_target_variable = "snap"

    # When: Parsing the tracer output with a dictionary as the target variable
    result = test_service._parse_tracer_output(
        invalid_tracer_output, valid_target_variable
    )

    # Then: It should return an empty list
    expected_output = empty_tracer
    assert result == expected_output


def test_tracer_output_for_garbage_variable():
    # Given: A tracer output with various income types
    # and a target variable that is a malformed string
    invalid_target_variable_malformed_string = "<1500>"

    # When: Parsing the tracer output with a malformed string
    result = test_service._parse_tracer_output(
        valid_tracer_output, invalid_target_variable_malformed_string
    )

    # Then: It should return an empty list
    expected_output = empty_tracer
    assert result == expected_output


def test_tracer_output_for_missing_variable():
    # Given: A tracer output with various income types
    # and a target variable that does not exist in the tracer output
    missing_target_variable = "non_existent_variable"

    # When: Extracting the segment for a missing variable
    result = test_service._parse_tracer_output(
        valid_tracer_output, missing_target_variable
    )

    # Then: It should return an empty list since the variable is not present in the tracer output
    expected_output = empty_tracer
    assert result == expected_output


def test_tracer_output_for_empty_tracer():
    # Given: An empty tracer output list
    # and some target variable
    valid_target_variable = "snap"

    # When: Extracting from an empty output
    result = test_service._parse_tracer_output(
        empty_tracer, valid_target_variable
    )

    # Then: It should return an empty list since there is no data to parse
    expected_output = empty_tracer
    assert result == expected_output


def test_tracer_output_for_root_variable():
    # Given: A tracer output with various income types
    # and a root-level variable that serves as a container for multiple sub-variables
    valid_target_variable = "snap"

    # When: Extracting the entire segment
    result = test_service._parse_tracer_output(
        valid_tracer_output, valid_target_variable
    )

    # Then: It should return everything inside input tracer
    expected_output = spliced_valid_tracer_output_root_variable
    assert result == expected_output


def test_tracer_output_for_nested_variable():
    # Given: A tracer output with various income types
    # and a deeply nested variable in the hierarchy
    valid_target_variable = "takes_up_snap_if_eligible"

    # When: Extracting nested variable
    result = test_service._parse_tracer_output(
        valid_tracer_output, valid_target_variable
    )

    # Then: It should return segment for nested variable and its children
    expected_output = spliced_valid_tracer_output_nested_variable
    assert result == expected_output


def test_tracer_output_for_leaf_variable():
    # Given: A tracer output with various income types
    # and a target variable that has no child variables
    valid_target_variable = "snap_fpg"

    # When: Extracting leaf variable from tracer
    result = test_service._parse_tracer_output(
        valid_tracer_output, valid_target_variable
    )

    # Then: It should return only leaf variable since it has no children
    expected_output = spliced_valid_tracer_output_leaf_variable
    assert result == expected_output


def test_tracer_output_for_variable_that_is_substring_of_another():
    # Given: A tracer output with variables where one is a substring of another
    # and the target variable that's a substring of another variable
    target_variable = "snap_net_income"

    # When: Extracting the segment for this variable
    result = test_service._parse_tracer_output(
        valid_tracer_output, target_variable
    )

    # Then: It should return only the exact match for "snap_net_income", not "snap_net_income_fpg_ratio"

    expected_output = (
        spliced_valid_tracer_output_for_variable_that_is_substring_of_another
    )
    assert result == expected_output


def test_get_tracer_invalid_country_id():
    # Given: Invalid country_id format (not 2 characters)
    invalid_country_id = "usa"
    household_id = "1234"
    policy_id = "5678"
    api_version = "1.0.0"

    # When/Then: Getting a tracer with invalid country_id should raise ValueError
    with pytest.raises(
        ValueError, match="Invalid country_id: must be a 2-character string"
    ):
        test_service.get_tracer(
            invalid_country_id, household_id, policy_id, api_version
        )


def test_get_tracer_invalid_api_version():
    # Given: Invalid api_version format (not X.Y.Z)
    country_id = "us"
    household_id = "1234"
    policy_id = "5678"
    invalid_api_version = "invalid-version"

    # When/Then: Getting a tracer with invalid api_version should raise ValueError
    with pytest.raises(
        ValueError,
        match="Invalid api_version: must follow the format 'X.Y.Z'.",
    ):
        test_service.get_tracer(
            country_id, household_id, policy_id, invalid_api_version
        )


def test_get_tracer_invalid_household_id():
    # Given: Invalid household_id format (non-numeric)
    country_id = "us"
    invalid_household_id = "abc123"
    policy_id = "5678"
    api_version = "1.0.0"

    # When/Then: Getting a tracer with invalid household_id should raise ValueError
    with pytest.raises(
        ValueError,
        match="Invalid household_id: must be a numeric integer or string",
    ):
        test_service.get_tracer(
            country_id, invalid_household_id, policy_id, api_version
        )


def test_get_tracer_invalid_policy_id():
    # Given: Invalid policy_id format (non-numeric)
    country_id = "us"
    household_id = "1234"
    invalid_policy_id = "abc123"
    api_version = "1.0.0"

    # When/Then: Getting a tracer with invalid policy_id should raise ValueError
    with pytest.raises(
        ValueError,
        match="Invalid policy_id: must be a numeric integer or string",
    ):
        test_service.get_tracer(
            country_id, household_id, invalid_policy_id, api_version
        )
