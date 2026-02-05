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


def test_get_prompt_template_for_uk():
    # Given: UK country code
    country_id = "uk"

    # When: Getting the prompt template
    template = test_service._get_prompt_template(country_id)

    # Then: It should include £ currency symbol instruction
    assert "preface £ with \\." in template
    assert "preface $" not in template


def test_get_prompt_template_for_us():
    # Given: US country code
    country_id = "us"

    # When: Getting the prompt template
    template = test_service._get_prompt_template(country_id)

    # Then: It should include $ currency symbol instruction
    assert "preface $ with \\." in template
    assert "preface £" not in template


def test_get_prompt_template_for_canada():
    # Given: Canada country code
    country_id = "ca"

    # When: Getting the prompt template
    template = test_service._get_prompt_template(country_id)

    # Then: It should include $ currency symbol instruction
    assert "preface $ with \\." in template


def test_get_prompt_template_for_israel():
    # Given: Israel country code
    country_id = "il"

    # When: Getting the prompt template
    template = test_service._get_prompt_template(country_id)

    # Then: It should include ₪ currency symbol instruction
    assert "preface ₪ with \\." in template


def test_get_prompt_template_for_nigeria():
    # Given: Nigeria country code
    country_id = "ng"

    # When: Getting the prompt template
    template = test_service._get_prompt_template(country_id)

    # Then: It should include ₦ currency symbol instruction
    assert "preface ₦ with \\." in template


def test_get_prompt_template_for_unknown_country():
    # Given: Unknown country code
    country_id = "xx"

    # When: Getting the prompt template
    template = test_service._get_prompt_template(country_id)

    # Then: It should still return a valid template without currency-specific instruction
    assert "The response will be rendered as markdown." in template
    assert "preface" not in template or "with \\." not in template
