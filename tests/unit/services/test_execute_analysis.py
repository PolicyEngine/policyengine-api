import pytest
import json
from policyengine_api.services.tracer_analysis_service import (
    TracerAnalysisService,
)
from werkzeug.exceptions import NotFound

from tests.fixtures.services.tracer_analysis_service import (
    sample_tracer_data,
    sample_expected_segment,
    mock_get_tracer,
    mock_get_existing_analysis,
    mock_parse_tracer_output,
    mock_trigger_ai_analysis,
)

service = TracerAnalysisService()
country_id = "us"
household_id = "71424"
policy_id = "2"
target_variable = "takes_up_snap_if_eligible"


class TestExecuteAnalysis:
    def test_execute_analysis_static(
        self,
        mock_get_tracer,
        mock_parse_tracer_output,
        mock_get_existing_analysis,
    ):
        """
        GIVEN a valid tracer data and an expected parsed segment (included as fixture),
        AND get_existing_analysis returns a static analysis (included as fixture),
        WHEN execute_analysis is called,
        THEN then a static analysis with the "static" flag should be returned.
        """

        analysis, analysis_type = service.execute_analysis(
            country_id, household_id, policy_id, target_variable
        )

        assert analysis == "Existing static analysis"
        assert analysis_type == "static"

    def test_execute_analysis_streaming(
        self,
        mock_get_tracer,
        mock_parse_tracer_output,
        mock_get_existing_analysis,
        mock_trigger_ai_analysis,
    ):
        """
        GIVEN a valid tracer data and an expected parsed segment,
        AND get_existing_analysis returns None,
        WHEN execute_analysis is called,
        THEN trigger_ai_analysis  is called and returns a generator with the "streaming" flag.
        """

        # When existing analysis value is None
        mock_get_existing_analysis.return_value = None

        analysis, analysis_type = service.execute_analysis(
            country_id, household_id, policy_id, target_variable
        )

        expected_streaming_output = ["stream chunk 1", "stream chunk 2"]
        streaming_output = list(analysis)
        assert streaming_output == expected_streaming_output
        assert analysis_type == "streaming"
