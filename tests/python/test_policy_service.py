import pytest
from unittest.mock import patch, MagicMock
import json
from policyengine_api.services.policy_service import PolicyService


@pytest.fixture
def mock_database():
    with patch("policyengine_api.services.policy_service.database") as mock_db:
        yield mock_db


@pytest.fixture
def sample_policy_data():
    return {
        "id": 1,
        "country_id": "US",
        "policy_json": json.dumps({"param": "value"}),
        "policy_hash": "hash123",
        "label": "test_policy",
        "api_version": "1.0.0",
    }


@pytest.fixture
def policy_service():
    return PolicyService()


class TestPolicyService:

    test_policy_id = 8  # Arbitrary value higher than 5

    def test_get_policy_success(
        self, policy_service, mock_database, sample_policy_data
    ):
        # Setup mock
        mock_database.query.return_value.fetchone.return_value = (
            sample_policy_data
        )

        # Test
        result = policy_service.get_policy("us", self.test_policy_id)

        # Verify
        assert result is not None
        assert isinstance(result["policy_json"], dict)
        assert result["policy_json"]["param"] == "value"
        mock_database.query.assert_called_once_with(
            "SELECT * FROM policy WHERE country_id = ? AND id = ?",
            ("us", self.test_policy_id),
        )

    def test_get_policy_not_found(self, policy_service, mock_database):
        # Setup mock
        mock_database.query.return_value.fetchone.return_value = None

        # Test
        garbage_id = 999
        result = policy_service.get_policy("us", garbage_id)

        # Verify
        assert result is None
        mock_database.query.assert_called_once()

    def test_get_policy_json(
        self, policy_service, mock_database, sample_policy_data
    ):
        # Setup mock
        mock_database.query.return_value.fetchone.return_value = {
            "policy_json": sample_policy_data["policy_json"]
        }

        # Test
        result = policy_service.get_policy_json("us", self.test_policy_id)

        # Verify
        assert result == sample_policy_data["policy_json"]
        mock_database.query.assert_called_once()

    def test_set_policy_new(self, policy_service, mock_database):
        new_policy_id = 10

        # Setup mocks
        mock_database.query.return_value.fetchone.side_effect = [
            None,  # First call for existing policy check
            {"id": new_policy_id},  # Second call to get new policy
        ]

        test_policy = {"param": "value"}

        # Test
        policy_id, message, exists = policy_service.set_policy(
            "US", "new_policy", test_policy
        )

        # Verify
        assert policy_id == new_policy_id
        assert message == "Policy created"
        assert exists is False
        assert (
            mock_database.query.call_count == 3
        )  # Check exists + Insert + Get new policy

    def test_set_policy_existing(
        self, policy_service, mock_database, sample_policy_data
    ):
        # Setup mock
        mock_database.query.return_value.fetchone.return_value = (
            sample_policy_data
        )

        # Test
        policy_id, message, exists = policy_service.set_policy(
            "us",
            sample_policy_data["label"],
            json.loads(sample_policy_data["policy_json"]),
        )

        # Verify
        assert policy_id == sample_policy_data["id"]
        assert message == "Policy already exists"
        assert exists is True
        mock_database.query.assert_called_once()

    def test_get_unique_policy_with_label(
        self, policy_service, mock_database, sample_policy_data
    ):
        # Setup mock
        mock_database.query.return_value.fetchone.return_value = (
            sample_policy_data
        )

        # Test
        result = policy_service._get_unique_policy_with_label(
            "us",
            sample_policy_data["policy_hash"],
            sample_policy_data["label"],
        )

        # Verify
        assert result == sample_policy_data
        mock_database.query.assert_called_once()

    def test_get_unique_policy_with_null_label(
        self, policy_service, mock_database
    ):
        # Setup mock
        mock_database.query.return_value.fetchone.return_value = None

        # Test
        result = policy_service._get_unique_policy_with_label(
            "us", "hash123", None
        )

        # Verify
        assert result is None
        mock_database.query.assert_called_once_with(
            "SELECT * FROM policy WHERE country_id = ? AND policy_hash = ? AND label IS NULL",
            ("us", "hash123"),
        )

    @pytest.mark.parametrize(
        "error_method",
        [
            "get_policy",
            "get_policy_json",
            "set_policy",
            "_get_unique_policy_with_label",
        ],
    )
    def test_error_handling(self, policy_service, mock_database, error_method):
        # Setup mock to raise exception
        mock_database.query.side_effect = Exception("Database error")

        # Test
        with pytest.raises(Exception) as exc_info:
            if error_method == "get_policy":
                policy_service.get_policy("us", 1)
            elif error_method == "get_policy_json":
                policy_service.get_policy_json("us", 1)
            elif error_method == "set_policy":
                policy_service.set_policy("us", "label", {})
            else:
                policy_service._get_unique_policy_with_label(
                    "us", "hash", "label"
                )

        assert str(exc_info.value) == "Database error"
