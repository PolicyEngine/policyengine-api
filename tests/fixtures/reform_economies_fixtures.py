import pytest
import json
from unittest.mock import patch

from policyengine_api.services.policy_service import PolicyService
from tests.data.test_reforms_states import all_policies as all_policies_states
from tests.data.test_reforms_uk import all_policies as all_policies_uk
from tests.data.test_reforms_us import all_policies as all_policies_us

policy_service = PolicyService()


class MockPolicyService:
    def __init__(self, test_policy):
        self.test_policy = test_policy

    def get_policy_json(self, country_id, policy_id):
        # If the policy ID matches with any current law value,
        # return an empty dict, else return test_policy
        if 1 <= policy_id <= 5:
            return json.dumps({})
        return json.dumps(self.test_policy["data"])


@pytest.fixture
def mock_all_services(reform):
    with patch.multiple(
        "policyengine_api.services.economy_service",
        policy_service=MockPolicyService(reform),
    ):
        yield {"policy_service": policy_service}


def prepare_us_reforms():
    reforms = []
    for policy in all_policies_us:
        policy["country_id"] = "us"
        policy["region"] = "us"
        policy["current_law"] = 2
        reforms.append(policy)
    return reforms


def prepare_uk_reforms():
    reforms = []
    for reform in all_policies_uk:
        reform["country_id"] = "uk"
        reform["region"] = "uk"
        reform["current_law"] = 1
        reforms.append(reform)
    return reforms


def prepare_state_reforms():
    reforms = []
    for reform in all_policies_states:
        reform["country_id"] = "us"
        reform["current_law"] = 2
        reforms.append(reform)
    return reforms
