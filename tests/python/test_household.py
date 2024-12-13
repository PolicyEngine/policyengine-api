import pytest
import json
from unittest.mock import MagicMock, patch
from sqlalchemy.engine.row import LegacyRow

from policyengine_api.routes.household_routes import household_bp
from policyengine_api.services.household_service import HouseholdService

from tests.fixtures.household_fixtures import (
    SAMPLE_HOUSEHOLD_DATA,
    SAMPLE_DB_ROW,
    mock_database,
    mock_hash_object,
)


class TestGetHousehold:
    def test_get_existing_household(self, rest_client, mock_database):
        """Test getting an existing household."""
        # Mock database response
        mock_row = MagicMock(spec=LegacyRow)
        mock_row.__getitem__.side_effect = lambda x: SAMPLE_DB_ROW[x]
        mock_row.keys.return_value = SAMPLE_DB_ROW.keys()
        mock_database.query().fetchone.return_value = mock_row

        # Make request
        response = rest_client.get("/us/household/1")
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["status"] == "ok"
        assert (
            data["result"]["household_json"] == SAMPLE_HOUSEHOLD_DATA["data"]
        )

    def test_get_nonexistent_household(self, rest_client, mock_database):
        """Test getting a non-existent household."""
        mock_database.query().fetchone.return_value = None

        response = rest_client.get("/us/household/999")
        print("Response:")
        print(response)
        data = json.loads(response.data)
        print("Data:")
        print(data)

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
        mock_row = MagicMock(spec=LegacyRow)
        mock_row.__getitem__.side_effect = lambda x: {"id": 1}[x]
        mock_database.query().fetchone.return_value = mock_row

        response = rest_client.post(
            "/us/household",
            json=SAMPLE_HOUSEHOLD_DATA,
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
        mock_row = MagicMock(spec=LegacyRow)
        mock_row.__getitem__.side_effect = lambda x: SAMPLE_DB_ROW[x]
        mock_row.keys.return_value = SAMPLE_DB_ROW.keys()
        mock_database.query().fetchone.return_value = mock_row

        updated_data = {
            "data": {"people": {"person1": {"age": 31, "income": 55000}}},
            "label": "Updated Test Household",
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
        assert data["result"]["household_json"] == updated_data["data"]

    def test_update_nonexistent_household(self, rest_client, mock_database):
        """Test updating a non-existent household."""
        mock_database.query().fetchone.return_value = None

        response = rest_client.put(
            "/us/household/999",
            json=SAMPLE_HOUSEHOLD_DATA,
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


# Service level tests
class TestHouseholdService:
    def test_get_household(self, mock_database):
        """Test HouseholdService.get_household method."""
        service = HouseholdService()

        # Mock database response
        mock_row = MagicMock(spec=LegacyRow)
        mock_row.__getitem__.side_effect = lambda x: SAMPLE_DB_ROW[x]
        mock_row.keys.return_value = SAMPLE_DB_ROW.keys()
        mock_database.query().fetchone.return_value = mock_row

        result = service.get_household("us", 1)

        assert result is not None
        assert result["household_json"] == SAMPLE_HOUSEHOLD_DATA["data"]

    def test_create_household(self, mock_database, mock_hash_object):
        """Test HouseholdService.create_household method."""
        service = HouseholdService()

        # Mock database response for the ID query
        mock_row = MagicMock(spec=LegacyRow)
        mock_row.__getitem__.side_effect = lambda x: {"id": 1}[x]
        mock_database.query().fetchone.return_value = mock_row

        household_id = service.create_household(
            "us", SAMPLE_HOUSEHOLD_DATA["data"], SAMPLE_HOUSEHOLD_DATA["label"]
        )

        assert household_id == 1
        mock_database.query.assert_called()

    def test_update_household(self, mock_database, mock_hash_object):
        """Test HouseholdService.update_household method."""
        service = HouseholdService()

        service.update_household(
            "us",
            "1",
            SAMPLE_HOUSEHOLD_DATA["data"],
            SAMPLE_HOUSEHOLD_DATA["label"],
        )

        mock_database.query.assert_called()
        assert mock_hash_object.called


class TestHouseholdRouteValidation:
    """Test validation and error handling in household routes."""

    @pytest.mark.parametrize(
        "invalid_payload",
        [
            {},  # Empty payload
            {"label": "Test"},  # Missing data field
            {"data": None},  # None data
            {"data": "not_a_dict"},  # Non-dict data
            {"data": {}, "label": 123},  # Invalid label type
        ],
    )
    def test_post_household_invalid_payload(
        self, rest_client, invalid_payload
    ):
        """Test POST endpoint with various invalid payloads."""
        response = rest_client.post(
            "/us/household",
            json=invalid_payload,
            content_type="application/json",
        )

        assert response.status_code == 400
        assert b"Unable to create new household" in response.data

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "abc",  # Non-numeric
            "1.5",  # Float
        ],
    )
    def test_get_household_invalid_id(self, rest_client, invalid_id):
        """Test GET endpoint with invalid household IDs."""
        response = rest_client.get(f"/us/household/{invalid_id}")
        print(response)
        print(response.data)

        # Default Werkzeug validation returns 404, not 400
        assert response.status_code == 404
        assert (
            b"The requested URL was not found on the server" in response.data
        )

    @pytest.mark.parametrize(
        "country_id",
        [
            "123",  # Numeric
            "us!!",  # Special characters
            "zz",  # Non-ISO
            "a" * 100,  # Too long
        ],
    )
    def test_invalid_country_id(self, rest_client, country_id):
        """Test endpoints with invalid country IDs."""
        # Test GET
        get_response = rest_client.get(f"/{country_id}/household/1")
        assert get_response.status_code == 400

        # Test POST
        post_response = rest_client.post(
            f"/{country_id}/household",
            json={"data": {}},
            content_type="application/json",
        )
        assert post_response.status_code == 400

        # Test PUT
        put_response = rest_client.put(
            f"/{country_id}/household/1",
            json={"data": {}},
            content_type="application/json",
        )
        assert put_response.status_code == 400


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
