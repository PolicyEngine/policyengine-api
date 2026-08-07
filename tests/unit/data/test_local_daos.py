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
    with uow.transaction() as daos:
        daos.analyses.store("prompt", "answer", "complete")
    with uow.read() as daos:
        assert daos.analyses.get("prompt") == "answer"


def test_reform_impact_dao_transitions_by_execution_id():
    uow = _unit_of_work()
    with uow.transaction() as daos:
        daos.reform_impacts.create(
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
        daos.reform_impacts.complete("job", {"result": 1}, datetime(2026, 1, 2))
    with uow.read() as daos:
        assert daos.reform_impacts.find(execution_id="job")["status"] == "ok"
        assert daos.reform_impacts.find(execution_id="job")["reform_impact_json"] == {
            "result": 1
        }


def test_reform_impact_dao_orders_limits_messages_and_handles_missing_jobs():
    uow = _unit_of_work()
    with uow.transaction() as daos:
        for day, execution_id in ((1, "old-job"), (2, "new-job")):
            daos.reform_impacts.create(
                country_id="us",
                reform_policy_id=2,
                baseline_policy_id=1,
                region="us",
                dataset="default",
                time_period="2026",
                options_json={},
                options_hash=execution_id,
                api_version="1",
                reform_impact_json={},
                status="computing",
                start_time=datetime(2026, 1, day),
                execution_id=execution_id,
            )

        assert daos.reform_impacts.set_message(
            "queued", country_id="us", status="computing"
        )
        assert daos.reform_impacts.set_message("missing", country_id="uk") is False
        assert (
            daos.reform_impacts.fail("missing-job", "failed", datetime(2026, 1, 3))
            is False
        )
        assert (
            daos.reform_impacts.complete("missing-job", {}, datetime(2026, 1, 3))
            is False
        )

    with uow.read() as daos:
        recent = daos.reform_impacts.list_recent(1)
        assert [row["execution_id"] for row in recent] == ["new-job"]
        assert recent[0]["message"] == "queued"


def test_tracer_dao_returns_latest_matching_trace():
    uow = _unit_of_work()
    with uow.transaction() as daos:
        daos.tracers.create(1, 2, "us", "1", {"trace": "first"})
        daos.tracers.create(1, 2, "us", "1", {"trace": "latest"})
    with uow.read() as daos:
        assert daos.tracers.get(1, 2, "us")["tracer_output"] == {"trace": "latest"}
