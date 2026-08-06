from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import HouseholdDAO, PolicyDAO, UserDAO
from policyengine_api.data.v1_models import V1Base


def _daos():
    manager = build_sqlite_session_manager()
    V1Base.metadata.create_all(manager.engine)
    return PolicyDAO(manager), HouseholdDAO(manager), UserDAO(manager)


def test_policy_dao_round_trips_legacy_mapping_shape():
    policies, _, _ = _daos()
    policy_id = policies.create("us", "Reform", {"gov.irs": 1}, "hash", "1.0")
    assert policy_id == 1
    assert policies.get("us", policy_id) == {
        "id": 1,
        "country_id": "us",
        "label": "Reform",
        "api_version": "1.0",
        "policy_json": {"gov.irs": 1},
        "policy_hash": "hash",
    }


def test_policy_dao_allocates_ids_and_detects_existing_policy():
    policies, _, _ = _daos()
    assert policies.create("us", None, {}, "one", "1.0") == 1
    assert policies.create("uk", None, {}, "two", "1.0") == 2
    assert policies.find_unique("us", "one", None)["id"] == 1


def test_household_dao_creates_updates_and_reads():
    _, households, _ = _daos()
    household_id = households.create("us", "Home", {"people": {}}, "h", "1.0")
    households.update("us", household_id, "Updated", {"people": {"you": {}}})
    assert households.get("us", household_id)["label"] == "Updated"
    assert households.get("uk", household_id) is None


def test_user_dao_profile_lookup_precedence():
    _, _, users = _daos()
    user_id = users.create_profile("auth0|one", "person", "us", 123)
    assert users.get_profile(auth0_id="auth0|one")["user_id"] == user_id
    assert users.get_profile(user_id=user_id, auth0_id="wrong")["auth0_id"] == "auth0|one"
