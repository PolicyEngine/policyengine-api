from datetime import datetime

from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import V1UnitOfWork
from tests.unit.data.sqlite_schema import create_sqlite_v1_schema


def _unit_of_work():
    manager = build_sqlite_session_manager()
    create_sqlite_v1_schema(manager)
    return V1UnitOfWork(manager)


def test_analysis_dao_round_trip():
    uow = _unit_of_work()
    with uow.transaction() as repositories:
        repositories.analyses.store("prompt", "answer", "complete")
    with uow.read() as repositories:
        assert repositories.analyses.get("prompt") == "answer"


def test_reform_impact_dao_transitions_by_execution_id():
    uow = _unit_of_work()
    with uow.transaction() as repositories:
        repositories.reform_impacts.create(
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
        repositories.reform_impacts.complete("job", {"result": 1}, datetime(2026, 1, 2))
    with uow.read() as repositories:
        assert repositories.reform_impacts.find(execution_id="job")["status"] == "ok"
        assert repositories.reform_impacts.find(execution_id="job")[
            "reform_impact_json"
        ] == {"result": 1}


def test_tracer_dao_returns_latest_matching_trace():
    uow = _unit_of_work()
    with uow.transaction() as repositories:
        repositories.tracers.create(1, 2, "us", "1", {"trace": "first"})
        repositories.tracers.create(1, 2, "us", "1", {"trace": "latest"})
    with uow.read() as repositories:
        assert repositories.tracers.get(1, 2, "us")["tracer_output"] == {
            "trace": "latest"
        }
