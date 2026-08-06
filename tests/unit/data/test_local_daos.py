from datetime import datetime

from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import AnalysisDAO, ReformImpactDAO, TracerDAO
from policyengine_api.data.v1_models import V1Base


def _daos():
    manager = build_sqlite_session_manager()
    V1Base.metadata.create_all(manager.engine)
    return AnalysisDAO(manager), ReformImpactDAO(manager), TracerDAO(manager)


def test_analysis_dao_round_trip():
    analyses, _, _ = _daos()
    analyses.store("prompt", "answer", "complete")
    assert analyses.get("prompt") == "answer"


def test_reform_impact_dao_transitions_by_execution_id():
    _, impacts, _ = _daos()
    impacts.create(
        country_id="us",
        reform_policy_id=2,
        baseline_policy_id=1,
        region="us",
        dataset="default",
        time_period="2026",
        options_json={},
        options_hash="hash",
        api_version="1",
        reform_impact_json={},
        status="computing",
        start_time=datetime(2026, 1, 1),
        execution_id="job",
    )
    impacts.complete("job", {"result": 1}, datetime(2026, 1, 2))
    assert impacts.find(execution_id="job")["status"] == "ok"
    assert impacts.find(execution_id="job")["reform_impact_json"] == {"result": 1}


def test_tracer_dao_returns_latest_matching_trace():
    _, _, tracers = _daos()
    tracers.create(1, 2, "us", "1", {"trace": "first"})
    tracers.create(1, 2, "us", "1", {"trace": "latest"})
    assert tracers.get(1, 2, "us")["tracer_output"] == {"trace": "latest"}
