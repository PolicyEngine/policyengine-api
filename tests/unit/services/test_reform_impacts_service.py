from datetime import datetime

from sqlalchemy import select

from policyengine_api.data.v1_models import ReformImpact
from policyengine_api.services.reform_impacts_service import ReformImpactsService


service = ReformImpactsService()


def _create_impact(session, *, execution_id: str, options_hash: str, day: int):
    return service.set_reform_impact(
        session,
        country_id="us",
        policy_id=2,
        baseline_policy_id=1,
        region="us",
        dataset="default",
        time_period="2026",
        options={"hash": options_hash},
        options_hash=options_hash,
        status="computing",
        api_version="1",
        reform_impact_json={},
        start_time=datetime(2026, 1, day),
        execution_id=execution_id,
    )


def test_reform_impact_service_round_trips_models_and_transitions(orm_session):
    exact = _create_impact(
        orm_session,
        execution_id="exact-job",
        options_hash="hash-exact",
        day=1,
    )
    compatible = _create_impact(
        orm_session,
        execution_id="compatible-job",
        options_hash="hash-compatible",
        day=2,
    )

    exact_results = service.get_all_reform_impacts(
        orm_session,
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "hash-exact",
        "1",
    )
    compatible_results = service.get_all_reform_impacts_by_options_hash_prefix(
        orm_session,
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "hash-exact",
        "hash-%",
        "1",
    )

    assert exact_results == [exact]
    assert compatible_results == [exact, compatible]
    completed = service.set_complete_reform_impact(
        orm_session,
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "hash-exact",
        {"result": 1},
        "exact-job",
    )
    failed = service.set_error_reform_impact(
        orm_session,
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "hash-compatible",
        "failed",
        "compatible-job",
    )

    assert completed.status == "ok"
    assert completed.reform_impact_json == {"result": 1}
    assert failed.status == "error"
    assert failed.message == "failed"


def test_reform_impact_service_deletes_only_matching_computing_rows(orm_session):
    _create_impact(
        orm_session,
        execution_id="delete-job",
        options_hash="delete-hash",
        day=1,
    )
    retained = _create_impact(
        orm_session,
        execution_id="retain-job",
        options_hash="retain-hash",
        day=2,
    )

    service.delete_reform_impact(
        orm_session,
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "delete-hash",
    )

    assert (
        orm_session.scalar(
            select(ReformImpact).where(ReformImpact.execution_id == "delete-job")
        )
        is None
    )
    assert orm_session.get(ReformImpact, retained.reform_impact_id) is retained


def test_reform_impact_transitions_return_none_for_missing_execution(orm_session):
    assert (
        service.set_error_reform_impact(
            orm_session,
            "us",
            2,
            1,
            "us",
            "default",
            "2026",
            "hash",
            "missing",
            "missing-job",
        )
        is None
    )
