from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import V1UnitOfWork
from tests.unit.data.sqlite_schema import create_sqlite_v1_schema


def _unit_of_work():
    manager = build_sqlite_session_manager()
    create_sqlite_v1_schema(manager)
    return V1UnitOfWork(manager)


def test_policy_dao_round_trips_legacy_mapping_shape():
    uow = _unit_of_work()
    with uow.transaction() as daos:
        policy_id = daos.policies.create("us", "Reform", {"gov.irs": 1}, "hash", "1.0")
    with uow.read() as daos:
        assert policy_id == 1
        assert daos.policies.get("us", policy_id) == {
            "id": 1,
            "country_id": "us",
            "label": "Reform",
            "api_version": "1.0",
            "policy_json": {"gov.irs": 1},
            "policy_hash": "hash",
        }


def test_policy_dao_allocates_ids_and_detects_existing_policy():
    uow = _unit_of_work()
    with uow.transaction() as daos:
        assert daos.policies.create("us", None, {}, "one", "1.0") == 1
        assert daos.policies.create("uk", None, {}, "two", "1.0") == 2
    with uow.read() as daos:
        assert daos.policies.find_unique("us", "one", None)["id"] == 1


def test_household_dao_creates_updates_and_reads():
    uow = _unit_of_work()
    with uow.transaction() as daos:
        household_id = daos.households.create("us", "Home", {"people": {}}, "h", "1.0")
        daos.households.update(
            "us",
            household_id,
            "Updated",
            {"people": {"you": {}}},
            "updated-hash",
            "2.0",
        )
    with uow.read() as daos:
        assert daos.households.get("us", household_id)["label"] == "Updated"
        assert daos.households.get("uk", household_id) is None


def test_user_dao_profile_lookup_precedence():
    uow = _unit_of_work()
    with uow.transaction() as daos:
        user_id = daos.users.create_profile("auth0|one", "person", "us", 123)
    with uow.read() as daos:
        assert daos.users.get_profile(auth0_id="auth0|one")["user_id"] == user_id
        assert (
            daos.users.get_profile(user_id=user_id, auth0_id="wrong")["auth0_id"]
            == "auth0|one"
        )


def test_user_and_household_daos_handle_missing_and_nullable_updates():
    uow = _unit_of_work()
    with uow.transaction() as daos:
        user_id = daos.users.create_profile("auth0|one", "original", "us", 123)
        assert daos.users.get_profile() is None
        assert daos.users.update_profile(999, username="missing") is False
        assert daos.households.update("us", 999, "missing", {}, "missing", "1") is False
        assert daos.users.update_profile(
            user_id,
            username=None,
            primary_country="uk",
        )

    with uow.read() as daos:
        profile = daos.users.get_profile(user_id=user_id)
        assert profile["username"] == "original"
        assert profile["primary_country"] == "uk"
