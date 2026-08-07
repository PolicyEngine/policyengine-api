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
    with uow.transaction() as repositories:
        repositories.computed_households.upsert(**values)
        repositories.computed_households.upsert(
            **{**values, "computed_household_json": {"value": 2}}
        )
    with uow.read() as repositories:
        row = repositories.computed_households.get(1, 2, "us", api_version="1")
        assert row["computed_household_json"] == {"value": 2}


def test_user_policy_nullable_identity_list_and_update_are_orm_managed():
    uow = _unit_of_work()
    values = {
        "country_id": "us",
        "reform_id": 2,
        "reform_label": None,
        "baseline_id": 1,
        "baseline_label": None,
        "user_id": "auth0|one",
        "year": "2026",
        "geography": "us",
        "dataset": None,
        "number_of_provisions": 3,
        "api_version": "1",
        "added_date": 1,
        "updated_date": 1,
        "budgetary_impact": None,
        "type": None,
    }
    with uow.transaction() as repositories:
        user_policy_id = repositories.user_policies.create(**values)
        assert repositories.user_policies.find_unique(**values)["id"] == user_policy_id
        assert repositories.user_policies.update(
            user_policy_id, {"number_of_provisions": 4}
        )
    with uow.read() as repositories:
        rows = repositories.user_policies.list_for_user("us", "auth0|one")
        assert rows[0]["number_of_provisions"] == 4


def test_policy_search_and_reform_impact_limit_use_typed_statements():
    uow = _unit_of_work()
    with uow.transaction() as repositories:
        repositories.policies.create("us", "Tax reform", {}, "one", "1")
        repositories.policies.create("us", "Other", {}, "two", "1")
    with uow.read() as repositories:
        assert [row["label"] for row in repositories.policies.search("us", "Tax")] == [
            "Tax reform"
        ]


def test_computed_household_create_and_version_filters():
    uow = _unit_of_work()
    with uow.transaction() as repositories:
        repositories.computed_households.create(
            household_id=1,
            policy_id=2,
            country_id="us",
            api_version="1",
            computed_household_json={"value": 1},
            status="complete",
        )

    with uow.read() as repositories:
        assert repositories.computed_households.get(1, 2, "us")[
            "computed_household_json"
        ] == {"value": 1}
        assert repositories.computed_households.get(1, 2, "us", api_version="2") is None


def test_economy_and_user_policy_daos_cover_lookup_edge_cases():
    uow = _unit_of_work()
    user_policy_values = {
        "country_id": "us",
        "reform_id": 2,
        "reform_label": None,
        "baseline_id": 1,
        "baseline_label": None,
        "user_id": "auth0|one",
        "year": "2026",
        "geography": "us",
        "dataset": None,
        "number_of_provisions": 3,
        "api_version": "1",
        "added_date": 1,
        "updated_date": 1,
        "budgetary_impact": None,
        "type": None,
    }
    with uow.transaction() as repositories:
        economy_id = repositories.economies.create(
            policy_id=2,
            country_id="us",
            region="us",
            time_period="2026",
            options_json={"dataset": "default"},
            options_hash="hash",
            api_version="1",
            economy_json={"result": 1},
            status="complete",
            message=None,
        )
        user_policy_id = repositories.user_policies.create(**user_policy_values)
        assert repositories.user_policies.update(999, {}) is False

    with uow.read() as repositories:
        assert repositories.economies.get(economy_id)["economy_json"] == {"result": 1}
        assert repositories.economies.get(999) is None
        assert repositories.user_policies.get(user_policy_id)["country_id"] == "us"
        assert repositories.user_policies.get(999) is None
