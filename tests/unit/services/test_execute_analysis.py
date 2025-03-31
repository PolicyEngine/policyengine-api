import pytest
import json
from policyengine_api.services.tracer_analysis_service import (
    TracerAnalysisService,
)
from werkzeug.exceptions import NotFound

from tests.fixtures.services.tracer_analysis_service_fixture import (
    sample_tracer_data,
    sample_expected_segment,
    get_tracer,
    get_existing_analysis,
    parse_tracer_output,
    trigger_ai_analysis,
)

service = TracerAnalysisService()


class TestExecuteAnalysis:
    def test_execute_analysis_static(
        self, get_tracer, parse_tracer_output, get_existing_analysis
    ):
        """
        GIVEN a valid tracer data and an expected parsed segment (included as fixture),
        AND get_existing_analysis returns a static analysis (included as fixture),
        WHEN execute_analysis is called,
        THEN then a static analysis with the "static" flag should be returned.
        """

        analysis, analysis_type = service.execute_analysis(
            "us", "71424", "2", "market_income"
        )

        assert analysis == "Existing static analysis"
        assert analysis_type == "static"

    def test_execute_analysis_streaming(
        self,
        get_tracer,
        parse_tracer_output,
        get_existing_analysis,
        trigger_ai_analysis,
    ):
        """
        GIVEN a valid tracer data and an expected parsed segment,
        AND get_existing_analysis returns None,
        WHEN execute_analysis is called ",
        THEN trigger_ai_analysis  is called and returns a generator with the "streaming" flag.
        """

        # When existing analysis value is None
        get_existing_analysis.return_value = None

        analysis, analysis_type = service.execute_analysis(
            "us", "71424", "2", "market_income"
        )

        streaming_output = list(analysis)
        assert streaming_output == ["stream chunk 1", "stream chunk 2"]
        assert analysis_type == "streaming"
