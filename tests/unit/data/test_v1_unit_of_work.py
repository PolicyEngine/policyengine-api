import pytest

from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import V1UnitOfWork
from tests.unit.data.sqlite_schema import create_sqlite_v1_schema


def _unit_of_work() -> V1UnitOfWork:
    manager = build_sqlite_session_manager()
    create_sqlite_v1_schema(manager)
    return V1UnitOfWork(manager)


def test_unit_of_work_commits_all_repositories_once():
    uow = _unit_of_work()

    with uow.transaction() as repositories:
        policy_id = repositories.policies.create("us", None, {}, "policy", "1")
        household_id = repositories.households.create("us", None, {}, "household", "1")

    with uow.read() as repositories:
        assert repositories.policies.get("us", policy_id) is not None
        assert repositories.households.get("us", household_id) is not None


def test_unit_of_work_rolls_back_every_repository_on_failure():
    uow = _unit_of_work()

    with pytest.raises(RuntimeError, match="abort"):
        with uow.transaction() as repositories:
            repositories.policies.create("us", None, {}, "policy", "1")
            repositories.users.create_profile("auth0|one", "person", "us", 1)
            raise RuntimeError("abort")

    with uow.read() as repositories:
        assert repositories.policies.get("us", 1) is None
        assert repositories.users.get_profile(auth0_id="auth0|one") is None
