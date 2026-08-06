import json
from unittest.mock import MagicMock

from assertpy import assert_that
import pytest

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.services.policy_service import PolicyService


@pytest.fixture
def policies():
    return MagicMock()


@pytest.fixture
def sample_policy_data():
    return {
        "id": 1,
        "country_id": "us",
        "policy_json": {"param": "value"},
        "policy_hash": "hash123",
        "label": "test_policy",
        "api_version": "1.0.0",
    }


@pytest.fixture
def policy_service(policies):
    return PolicyService(policies)


class TestPolicyService:
    a_test_policy_id = 8

    def test_get_policy_success(self, policy_service, policies, sample_policy_data):
        policies.get.return_value = sample_policy_data

        result = policy_service.get_policy("us", self.a_test_policy_id)

        assert_that(result).contains_entry({"policy_json": {"param": "value"}})
        policies.get.assert_called_once_with("us", self.a_test_policy_id)

    def test_get_policy_not_found(self, policy_service, policies):
        policies.get.return_value = None

        assert policy_service.get_policy("us", 999) is None
        policies.get.assert_called_once_with("us", 999)

    def test_get_policy_json(self, policy_service, policies, sample_policy_data):
        policies.get.return_value = sample_policy_data

        result = policy_service.get_policy_json("us", self.a_test_policy_id)

        assert result == json.dumps(sample_policy_data["policy_json"])
        policies.get.assert_called_once_with("us", self.a_test_policy_id)

    def test_set_policy_new(self, policy_service, policies):
        policies.find_unique.return_value = None
        policies.create.return_value = 10
        test_policy = {"param": "value"}

        policy_id, message, exists = policy_service.set_policy(
            "us", "new_policy", test_policy
        )

        assert (policy_id, message, exists) == (10, "Policy created", False)
        policies.find_unique.assert_called_once()
        policy_hash = policies.find_unique.call_args.args[1]
        policies.create.assert_called_once_with(
            "us",
            "new_policy",
            test_policy,
            policy_hash,
            COUNTRY_PACKAGE_VERSIONS["us"],
        )

    def test_set_policy_existing(self, policy_service, policies, sample_policy_data):
        policies.find_unique.return_value = sample_policy_data

        result = policy_service.set_policy(
            "us",
            sample_policy_data["label"],
            sample_policy_data["policy_json"],
        )

        assert result == (sample_policy_data["id"], "Policy already exists", True)
        policies.create.assert_not_called()

    def test_get_unique_policy_with_label(
        self, policy_service, policies, sample_policy_data
    ):
        policies.find_unique.return_value = sample_policy_data

        result = policy_service._get_unique_policy_with_label(
            "us",
            sample_policy_data["policy_hash"],
            sample_policy_data["label"],
        )

        assert result == sample_policy_data
        policies.find_unique.assert_called_once_with(
            "us",
            sample_policy_data["policy_hash"],
            sample_policy_data["label"],
        )

    def test_get_unique_policy_with_null_label(self, policy_service, policies):
        policies.find_unique.return_value = None

        result = policy_service._get_unique_policy_with_label("us", "hash123", None)

        assert result is None
        policies.find_unique.assert_called_once_with("us", "hash123", None)

    @pytest.mark.parametrize(
        ("error_method", "repository_method"),
        [
            ("get_policy", "get"),
            ("get_policy_json", "get"),
            ("set_policy", "find_unique"),
            ("_get_unique_policy_with_label", "find_unique"),
        ],
    )
    def test_error_handling(
        self, policy_service, policies, error_method, repository_method
    ):
        getattr(policies, repository_method).side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            if error_method == "get_policy":
                policy_service.get_policy("us", 1)
            elif error_method == "get_policy_json":
                policy_service.get_policy_json("us", 1)
            elif error_method == "set_policy":
                policy_service.set_policy("us", "label", {})
            else:
                policy_service._get_unique_policy_with_label("us", "hash", "label")
