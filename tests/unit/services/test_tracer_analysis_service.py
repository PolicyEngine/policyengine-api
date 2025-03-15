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
    invalid_target_variable = 500

    # When: Parsing the tracer output with an invalid target variable
    result = test_service._parse_tracer_output(
        valid_tracer_output, invalid_target_variable
    )

    # Then: It should return an empty list
    expected_output = empty_tracer
    assert result == expected_output


def test_tracer_output_for_dict_input_tracer():
    # Given: A tracer output with various income types but is in invalid format (dict instead of list of string)
    # and a valid target variable
    valid_target_variable = "market_income"

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
    target_variable = "<1500>"

    # When: Parsing the tracer output with a malformed string
    result = test_service._parse_tracer_output(
        valid_tracer_output, target_variable
    )

    # Then: It should return an empty list
    expected_output = empty_tracer
    assert result == expected_output


def test_tracer_output_for_missing_variable():
    # Given: A tracer output with various income types
    # and a target variable that does not exist in the tracer output
    target_variable = "non_existent_variable"

    # When: Extracting the segment for a missing variable
    result = test_service._parse_tracer_output(
        valid_tracer_output, target_variable
    )

    # Then: It should return an empty list since the variable is not present in the tracer output
    expected_output = empty_tracer
    assert result == expected_output


def test_tracer_output_for_empty_variable():
    # Given: A tracer output with various income types
    # and an empty target variable
    empty_target_variable = ""

    # When: Extracting the segment for a missing variable
    result = test_service._parse_tracer_output(
        valid_tracer_output, empty_target_variable
    )

    # Then: It should return an empty list
    expected_output = empty_tracer
    assert result == expected_output


def test_tracer_output_for_empty_tracer():
    # Given: An empty tracer output list
    # and some target variable
    valid_target_variable = "market_income"

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
    valid_target_variable = "only_government_benefit"

    # When: Extracting the entire segment
    result = test_service._parse_tracer_output(
        valid_tracer_output, valid_target_variable
    )

    # Then: It should return everything inside "only_government_benefit"
    expected_output = valid_tracer_output
    assert result == expected_output


def test_tracer_output_for_nested_variable():
    # Given: A tracer output with various income types
    # and a deeply nested variable in the hierarchy
    valid_target_variable = "employment_income"

    # When: Extracting "employment_income"
    result = test_service._parse_tracer_output(
        valid_tracer_output, valid_target_variable
    )

    # Then: It should return "employment_income" as well as its nested "main_employment_income"
    expected_output = spliced_valid_tracer_output_employment_income
    assert result == expected_output


def test_tracer_output_for_leaf_variable():
    # Given: A tracer output with various income types
    # and a target variable that has no child variables
    valid_target_variable = "pension_income"

    # When: Extracting "pension_income"
    result = test_service._parse_tracer_output(
        valid_tracer_output, valid_target_variable
    )

    # Then: It should return only "pension_income" since it has no children
    expected_output = spliced_valid_tracer_output_pension_income
    assert result == expected_output


def test_tracer_output_for_suffixed_variable():
    # Given: A tracer output with various income types
    # and target variable that is a substring of another longer variable
    valid_target_variable = "main_employment_income"

    # When: Extracting "main_employment_income"
    result = test_service._parse_tracer_output(
        valid_tracer_output_with_suffixed_target_variable,
        valid_target_variable,
    )

    # Then: It should return only "main_employment_income" since it has no children
    expected_output = spliced_tracer_output_with_suffixed_target_variable
    assert result == expected_output
