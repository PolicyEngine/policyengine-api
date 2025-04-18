import pytest
import json
from policyengine_api.services.tracer_analysis_service import (
    TracerAnalysisService,
)
from unittest.mock import patch


valid_tracer_output = [
    "        snap<2027, (default)> = [6769.799]",
    "          snap<2027-01, (default)> = [561.117]",
    "            takes_up_snap_if_eligible<2027-01, (default)> = [ True]",
    "            snap_normal_allotment<2027-01, (default)> = [561.117]",
    "              is_snap_eligible<2027-01, (default)> = [ True]",
    "                meets_snap_net_income_test<2027-01, (default)> = [ True]",
    "                  snap_net_income_fpg_ratio<2027-01, (default)> = [0.]",
    "                    snap_net_income<2027-01, (default)> = [0.]",
    "                    snap_fpg<2027-01, (default)> = [1806.4779]",
]

invalid_tracer_output = {
    "variable": "only_government_benefit <1500>",
    "variable": "    market_income <1000>",
}

spliced_valid_tracer_output_root_variable = valid_tracer_output[0:]

spliced_valid_tracer_output_nested_variable = valid_tracer_output[2:3]

spliced_valid_tracer_output_leaf_variable = valid_tracer_output[8:]

spliced_valid_tracer_output_for_variable_that_is_substring_of_another = (
    valid_tracer_output[7:8]
)

empty_tracer = []


@pytest.fixture
def sample_tracer_data():
    return valid_tracer_output


@pytest.fixture
def sample_expected_segment():
    return spliced_valid_tracer_output_nested_variable


@pytest.fixture
def mock_get_tracer(sample_tracer_data):
    with patch.object(
        TracerAnalysisService, "get_tracer", return_value=sample_tracer_data
    ) as mock:
        yield mock


@pytest.fixture
def mock_parse_tracer_output(sample_expected_segment):
    with patch.object(
        TracerAnalysisService,
        "_parse_tracer_output",
        return_value=sample_expected_segment,
    ) as mock:
        yield mock


@pytest.fixture
def mock_get_existing_analysis():
    with patch.object(
        TracerAnalysisService,
        "get_existing_analysis",
        return_value="Existing static analysis",
    ) as mock:
        yield mock


@pytest.fixture
def mock_trigger_ai_analysis():
    def dummy_generator():
        yield "stream chunk 1"
        yield "stream chunk 2"

    with patch.object(
        TracerAnalysisService,
        "trigger_ai_analysis",
        return_value=dummy_generator(),
    ) as mock:
        yield mock
