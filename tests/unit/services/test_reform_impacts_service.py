from datetime import datetime
from unittest.mock import ANY, Mock

from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import ReformImpactDAO, V1UnitOfWork
from policyengine_api.services import reform_impacts_service as service_module
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from tests.unit.data.sqlite_schema import create_sqlite_v1_schema


def _unit_of_work() -> V1UnitOfWork:
    manager = build_sqlite_session_manager()
    create_sqlite_v1_schema(manager)
    return V1UnitOfWork(manager)


def _create_impact(
    service: ReformImpactsService,
    *,
    execution_id: str,
    options_hash: str,
    day: int,
) -> int:
    return service.set_reform_impact(
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


def test_reform_impact_service_round_trips_queries_and_transitions():
    service = ReformImpactsService(unit_of_work=_unit_of_work())
    exact_id = _create_impact(
        service,
        execution_id="exact-job",
        options_hash="hash-exact",
        day=1,
    )
    compatible_id = _create_impact(
        service,
        execution_id="compatible-job",
        options_hash="hash-compatible",
        day=2,
    )

    exact = service.get_all_reform_impacts(
        "us", 2, 1, "us", "default", "2026", "hash-exact", "1"
    )
    compatible = service.get_all_reform_impacts_by_options_hash_prefix(
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

    assert [row["reform_impact_id"] for row in exact] == [exact_id]
    assert [row["reform_impact_id"] for row in compatible] == [
        exact_id,
        compatible_id,
    ]
    assert service.set_complete_reform_impact(
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
    assert service.set_error_reform_impact(
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

    with service.unit_of_work.read() as daos:
        completed = daos.reform_impacts.find(execution_id="exact-job")
        failed = daos.reform_impacts.find(execution_id="compatible-job")
    assert completed["status"] == "ok"
    assert completed["reform_impact_json"] == {"result": 1}
    assert failed["status"] == "error"
    assert failed["message"] == "failed"


def test_reform_impact_service_deletes_only_matching_computing_rows():
    service = ReformImpactsService(unit_of_work=_unit_of_work())
    _create_impact(
        service,
        execution_id="delete-job",
        options_hash="delete-hash",
        day=1,
    )
    retained_id = _create_impact(
        service,
        execution_id="retain-job",
        options_hash="retain-hash",
        day=2,
    )

    service.delete_reform_impact("us", 2, 1, "us", "default", "2026", "delete-hash")

    assert (
        service.get_all_reform_impacts(
            "us", 2, 1, "us", "default", "2026", "delete-hash", "1"
        )
        == []
    )
    retained = service.get_all_reform_impacts(
        "us", 2, 1, "us", "default", "2026", "retain-hash", "1"
    )
    assert [row["reform_impact_id"] for row in retained] == [retained_id]


def test_reform_impact_service_supports_injected_repository():
    impacts = Mock(spec=ReformImpactDAO)
    impacts.fail.return_value = False
    service = ReformImpactsService(impacts)

    assert (
        service.set_error_reform_impact(
            "us", 2, 1, "us", "default", "2026", "hash", "missing", "job"
        )
        is False
    )
    impacts.fail.assert_called_once_with("job", "missing", ANY)


def test_reform_impact_service_builds_default_unit_of_work_once(monkeypatch):
    manager = build_sqlite_session_manager()
    build_manager = Mock(return_value=manager)
    monkeypatch.setattr(service_module, "build_v1_session_manager", build_manager)
    service = ReformImpactsService()

    first = service.unit_of_work

    assert service.unit_of_work is first
    build_manager.assert_called_once_with(local=True)
