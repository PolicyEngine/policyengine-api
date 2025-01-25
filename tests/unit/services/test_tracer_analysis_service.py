import pytest

from policyengine_api.services.tracer_analysis_service import (
    TracerAnalysisService,
)

test_service = TracerAnalysisService()


# Test cases for parse_tracer_output function
def test_parse_tracer_output():

    tracer_output = [
        "only_government_benefit <1500>",
        "    market_income <1000>",
        "        employment_income <1000>",
        "            main_employment_income <1000 >",
        "    non_market_income <500>",
        "        pension_income <500>",
    ]

    result = test_service._parse_tracer_output(
        tracer_output, "only_government_benefit"
    )
    assert result == tracer_output

    result = test_service._parse_tracer_output(tracer_output, "market_income")
    assert result == tracer_output[1:4]

    result = test_service._parse_tracer_output(
        tracer_output, "non_market_income"
    )
    assert result == tracer_output[4:]
