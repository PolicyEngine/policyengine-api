import pytest

from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import V1UnitOfWork
from tests.unit.data.sqlite_schema import create_sqlite_v1_schema


def _unit_of_work() -> V1UnitOfWork:
    manager = build_sqlite_session_manager()
    create_sqlite_v1_schema(manager)
    return V1UnitOfWork(manager)


def test_unit_of_work_commits_all_daos_once():
    uow = _unit_of_work()

    with uow.transaction() as daos:
        policy_id = daos.policies.create("us", None, {}, "policy", "1")
        household_id = daos.households.create("us", None, {}, "household", "1")

    with uow.read() as daos:
        assert daos.policies.get("us", policy_id) is not None
        assert daos.households.get("us", household_id) is not None


def test_unit_of_work_rolls_back_every_repository_on_failure():
    uow = _unit_of_work()

    with pytest.raises(RuntimeError, match="abort"):
        with uow.transaction() as daos:
            daos.policies.create("us", None, {}, "policy", "1")
            daos.users.create_profile("auth0|one", "person", "us", 1)
            raise RuntimeError("abort")

    with uow.read() as daos:
        assert daos.policies.get("us", 1) is None
        assert daos.users.get_profile(auth0_id="auth0|one") is None


def test_unit_of_work_rolls_back_parent_run_and_alias_together():
    uow = _unit_of_work()

    with pytest.raises(RuntimeError, match="abort report"):
        with uow.transaction() as daos:
            report_id = daos.reports.create(
                country_id="us",
                simulation_1_id=1,
                simulation_2_id=None,
                api_version="1",
                year="2026",
            )
            daos.reports.create_run(
                report_id,
                run_id="report-run",
                status="pending",
                trigger_type="create",
            )
            daos.reports.set_alias(99, report_id)
            raise RuntimeError("abort report")

    with uow.read() as daos:
        assert daos.reports.get(1) is None
        assert daos.reports.get_run("report-run") is None
        assert daos.reports.get_alias(99) is None
