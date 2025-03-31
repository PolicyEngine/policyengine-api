import pytest 
import json
from policyengine_api.services.tracer_analysis_service import TracerAnalysisService
from unittest.mock import patch

# Sample valid tracer record
valid_tracer_record = {
    "tracer_output": [
        "only_government_benefit <1500>",
        "    market_income <1000>",
        "        employment_income <1000>",
        "            main_employment_income <1000>",
        "    non_market_income <500>",
        "        pension_income <500>",
    ]
}

# The expected parsed segment for the target variable "market income"
expected_segment = [
    "    market_income <1000>",
    "        employment_income <1000>",
    "            main_employment_income <1000>",
]


@pytest.fixture
def sample_tracer_data():
    return valid_tracer_record["tracer_output"]

@pytest.fixture
def sample_expected_segment():
    return expected_segment


@pytest.fixture
def get_tracer(sample_tracer_data):
    with patch.object(TracerAnalysisService, 'get_tracer', return_value=sample_tracer_data) as mock:
        yield mock

@pytest.fixture
def parse_tracer_output(sample_expected_segment):
    with patch.object(TracerAnalysisService, '_parse_tracer_output', return_value=sample_expected_segment) as mock:
        yield mock


@pytest.fixture
def get_existing_analysis():
    with patch.object(TracerAnalysisService, 'get_existing_analysis', return_value="Existing static analysis") as mock:
        yield mock

@pytest.fixture
def trigger_ai_analysis():
    def dummy_generator():
        yield "stream chunk 1"
        yield "stream chunk 2"
    with patch.object(TracerAnalysisService, 'trigger_ai_analysis', return_value=dummy_generator()) as mock:
        yield mock