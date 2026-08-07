from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import V1UnitOfWork
from tests.unit.data.sqlite_schema import create_sqlite_v1_schema


def _unit_of_work() -> V1UnitOfWork:
    manager = build_sqlite_session_manager()
    create_sqlite_v1_schema(manager)
    return V1UnitOfWork(manager)


def test_computed_household_upsert_preserves_one_cache_row():
    uow = _unit_of_work()
    values = {
        "household_id": 1,
        "policy_id": 2,
        "country_id": "us",
        "api_version": "1",
        "computed_household_json": {"value": 1},
        "status": "complete",
    }
    with uow.transaction() as daos:
        daos.computed_households.upsert(**values)
        daos.computed_households.upsert(
            **{**values, "computed_household_json": {"value": 2}}
        )
    with uow.read() as daos:
        row = daos.computed_households.get(1, 2, "us", api_version="1")
        assert row["computed_household_json"] == {"value": 2}


def test_policy_search_and_reform_impact_limit_use_typed_statements():
    uow = _unit_of_work()
    with uow.transaction() as daos:
        daos.policies.create("us", "Tax reform", {}, "one", "1")
        daos.policies.create("us", "Other", {}, "two", "1")
    with uow.read() as daos:
        assert [row["label"] for row in daos.policies.search("us", "Tax")] == [
            "Tax reform"
        ]


def test_computed_household_create_and_version_filters():
    uow = _unit_of_work()
    with uow.transaction() as daos:
        daos.computed_households.create(
            household_id=1,
            policy_id=2,
            country_id="us",
            api_version="1",
            computed_household_json={"value": 1},
            status="complete",
        )

    with uow.read() as daos:
        assert daos.computed_households.get(1, 2, "us")["computed_household_json"] == {
            "value": 1
        }
        assert daos.computed_households.get(1, 2, "us", api_version="2") is None
