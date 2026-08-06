from pathlib import Path

import pytest

from policyengine_api.services.household_service import HouseholdService
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.user_service import UserService


SERVICE_ROOT = Path(__file__).parents[3] / "policyengine_api" / "services"


@pytest.mark.parametrize(
    "module_name",
    ["household_service.py", "policy_service.py", "user_service.py"],
)
def test_migrated_services_do_not_issue_queries_directly(module_name):
    source = (SERVICE_ROOT / module_name).read_text(encoding="utf-8")
    assert ".query(" not in source
    assert "from policyengine_api.data import database" not in source


class StubHouseholds:
    def get(self, country_id, household_id):
        return {"country_id": country_id, "id": household_id}


class StubPolicies:
    def get(self, country_id, policy_id):
        return {
            "country_id": country_id,
            "id": policy_id,
            "policy_json": {"already": "decoded"},
        }


class StubUsers:
    def get_profile(self, *, user_id=None, auth0_id=None):
        return {"user_id": user_id, "auth0_id": auth0_id}


def test_services_accept_explicit_daos_for_isolated_parity_tests():
    assert HouseholdService(StubHouseholds()).get_household("us", 3)["id"] == 3
    assert PolicyService(StubPolicies()).get_policy("us", 4)["policy_json"] == {
        "already": "decoded"
    }
    assert UserService(StubUsers()).get_profile(auth0_id="auth0|one") == {
        "user_id": None,
        "auth0_id": "auth0|one",
    }
