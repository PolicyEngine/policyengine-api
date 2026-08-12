from datetime import datetime

from policyengine_api.data.local_models import Tracer
from policyengine_api.data.v1_models import Analysis, ReformImpact
from policyengine_api.services.ai_analysis_service import AIAnalysisService
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from policyengine_api.services.tracer_analysis_service import TracerAnalysisService


def test_ai_analysis_service_returns_the_latest_mapped_analysis(
    orm_session,
    orm_session_factory,
):
    orm_session.add_all(
        [
            Analysis(prompt="prompt", analysis="old", status="ok"),
            Analysis(prompt="prompt", analysis="new", status="complete"),
        ]
    )
    orm_session.flush()

    orm_session.commit()
    analysis = AIAnalysisService(orm_session_factory).get_existing_analysis("prompt")

    assert isinstance(analysis, Analysis)
    assert analysis.analysis == "new"


def test_reform_impact_service_writes_mapped_entity(orm_session_factory):
    impact = ReformImpactsService(orm_session_factory).set_reform_impact(
        country_id="us",
        policy_id=2,
        baseline_policy_id=1,
        region="us",
        dataset="default",
        time_period="2026",
        options={"dataset": "default"},
        options_hash="hash",
        status="computing",
        api_version="1",
        reform_impact_json={},
        start_time=datetime(2026, 1, 1),
        execution_id="job",
    )

    assert isinstance(impact, ReformImpact)
    assert impact.options_json == {"dataset": "default"}


def test_tracer_service_reads_python_json_from_mapped_entity(
    orm_session,
    orm_session_factory,
):
    orm_session.add(
        Tracer(
            household_id=1,
            policy_id=2,
            country_id="us",
            api_version="1",
            tracer_output=["net_income <2026>", "  dependency"],
        )
    )
    orm_session.commit()

    tracer = TracerAnalysisService(orm_session_factory).get_tracer(
        "us",
        "1",
        "2",
        "1",
    )

    assert tracer == ["net_income <2026>", "  dependency"]
