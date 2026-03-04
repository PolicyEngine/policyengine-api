import pytest
import json
from unittest.mock import MagicMock, patch

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

from tests.to_refactor.fixtures.to_refactor_household_fixtures import (
    valid_request_body,
    valid_db_row,
    mock_database,
    mock_hash_object,
)


class TestGetHousehold:
    def test_get_existing_household(self, rest_client, mock_database):
        """Test getting an existing household."""
        # Mock database response as a dict-like object
        # (SQLAlchemy v2 Row objects support dict() via ._mapping)
        mock_row = MagicMock()
        mock_row.__getitem__.side_effect = lambda x: valid_db_row[x]
        mock_row.keys.return_value = valid_db_row.keys()
        mock_database.query().fetchone.return_value = mock_row

        # Make request
        response = rest_client.get("/us/household/1")
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["status"] == "ok"
        assert data["result"]["household_json"] == valid_request_body["data"]

    def test_get_nonexistent_household(self, rest_client, mock_database):
        """Test getting a non-existent household."""
        mock_database.query().fetchone.return_value = None

        response = rest_client.get("/us/household/999")
        data = json.loads(response.data)

        assert response.status_code == 404
        assert data["status"] == "error"
        assert "not found" in data["message"]

    def test_get_household_invalid_id(self, rest_client):
        """Test getting a household with invalid ID."""
        response = rest_client.get("/us/household/invalid")

        assert response.status_code == 404
        assert (
            b"The requested URL was not found on the server" in response.data
        )


class TestCreateHousehold:
    def test_create_household_success(
        self, rest_client, mock_database, mock_hash_object
    ):
        """Test successfully creating a new household."""
        # Mock database responses
        mock_row = MagicMock()
        mock_row.__getitem__.side_effect = lambda x: {"id": 1}[x]
        mock_database.query().fetchone.return_value = mock_row

        response = rest_client.post(
            "/us/household",
            json=valid_request_body,
            content_type="application/json",
        )
        data = json.loads(response.data)

        assert response.status_code == 201
        assert data["status"] == "ok"
        assert data["result"]["household_id"] == 1

    def test_create_household_invalid_payload(self, rest_client):
        """Test creating a household with invalid payload."""
        invalid_payload = {
            "label": "Test",
            # Missing required 'data' field
        }

        response = rest_client.post(
            "/us/household",
            json=invalid_payload,
            content_type="application/json",
        )

        assert response.status_code == 400
        assert b"Missing required keys" in response.data

    def test_create_household_invalid_label(self, rest_client):
        """Test creating a household with invalid label type."""
        invalid_payload = {
            "data": {},
            "label": 123,  # Should be string or None
        }

        response = rest_client.post(
            "/us/household",
            json=invalid_payload,
            content_type="application/json",
        )

        assert response.status_code == 400
        assert b"Label must be a string or None" in response.data


class TestUpdateHousehold:
    def test_update_household_success(
        self, rest_client, mock_database, mock_hash_object
    ):
        """Test successfully updating an existing household."""
        # Mock getting existing household
        mock_row = MagicMock()
        mock_row.__getitem__.side_effect = lambda x: valid_db_row[x]
        mock_row.keys.return_value = valid_db_row.keys()
        mock_database.query().fetchone.return_value = mock_row

        updated_household = {
            "people": {"person1": {"age": 31, "income": 55000}}
        }

        updated_data = {
            "data": updated_household,
            "label": valid_request_body["label"],
        }

        response = rest_client.put(
            "/us/household/1",
            json=updated_data,
            content_type="application/json",
        )
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["status"] == "ok"
        assert data["result"]["household_id"] == 1
        # assert data["result"]["household_json"] == updated_data["data"]
        mock_database.query.assert_any_call(
            "UPDATE household SET household_json = ?, household_hash = ?, label = ?, api_version = ? WHERE id = ?",
            (
                json.dumps(updated_household),
                "some-hash",
                valid_request_body["label"],
                COUNTRY_PACKAGE_VERSIONS.get("us"),
                1,
            ),
        )

    def test_update_nonexistent_household(self, rest_client, mock_database):
        """Test updating a non-existent household."""
        mock_database.query().fetchone.return_value = None

        response = rest_client.put(
            "/us/household/999",
            json=valid_request_body,
            content_type="application/json",
        )
        data = json.loads(response.data)

        assert response.status_code == 404
        assert data["status"] == "error"
        assert "not found" in data["message"]

    def test_update_household_invalid_payload(self, rest_client):
        """Test updating a household with invalid payload."""
        invalid_payload = {
            "label": "Test",
            # Missing required 'data' field
        }

        response = rest_client.put(
            "/us/household/1",
            json=invalid_payload,
            content_type="application/json",
        )

        assert response.status_code == 400
        assert b"Missing required keys" in response.data


class TestHouseholdRouteServiceErrors:
    """Test handling of service-level errors in routes."""

    @patch(
        "policyengine_api.services.household_service.HouseholdService.get_household"
    )
    def test_get_household_service_error(self, mock_get, rest_client):
        """Test GET endpoint when service raises an error."""
        mock_get.side_effect = Exception("Database connection failed")

        response = rest_client.get("/us/household/1")
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["status"] == "error"
        assert "Database connection failed" in data["message"]

    @patch(
        "policyengine_api.services.household_service.HouseholdService.create_household"
    )
    def test_post_household_service_error(self, mock_create, rest_client):
        """Test POST endpoint when service raises an error."""
        mock_create.side_effect = Exception("Failed to create household")

        response = rest_client.post(
            "/us/household",
            json={"data": {"valid": "payload"}},
            content_type="application/json",
        )
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["status"] == "error"
        assert "Failed to create household" in data["message"]

    @patch(
        "policyengine_api.services.household_service.HouseholdService.update_household"
    )
    def test_put_household_service_error(self, mock_update, rest_client):
        """Test PUT endpoint when service raises an error."""
        mock_update.side_effect = Exception("Failed to update household")

        # First mock the get_household call that checks existence
        with patch(
            "policyengine_api.services.household_service.HouseholdService.get_household"
        ) as mock_get:
            mock_get.return_value = {"id": 1}  # Simulate existing household

            response = rest_client.put(
                "/us/household/1",
                json={"data": {"valid": "payload"}},
                content_type="application/json",
            )
            data = json.loads(response.data)

            assert response.status_code == 500
            assert data["status"] == "error"
            assert "Failed to update household" in data["message"]

    def test_missing_json_body(self, rest_client):
        """Test endpoints when JSON body is missing."""
        # Test POST without JSON
        post_response = rest_client.post("/us/household")
        # Actually intercepted by server, which responds with 415,
        # before we can even return a 400
        assert post_response.status_code in [400, 415]

        # Test PUT without JSON
        put_response = rest_client.put("/us/household/1")
        assert put_response.status_code in [400, 415]

    def test_malformed_json_body(self, rest_client):
        """Test endpoints with malformed JSON body."""
        # Test POST with malformed JSON
        post_response = rest_client.post(
            "/us/household",
            data="invalid json{",
            content_type="application/json",
        )
        assert post_response.status_code == 400

        # Test PUT with malformed JSON
        put_response = rest_client.put(
            "/us/household/1",
            data="invalid json{",
            content_type="application/json",
        )
        assert put_response.status_code == 400
