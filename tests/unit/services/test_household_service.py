import pytest
import json
from unittest.mock import MagicMock, patch
from sqlalchemy.engine.row import LegacyRow

from policyengine_api.services.household_service import HouseholdService
from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

from tests.fixtures.household_fixtures import (
    SAMPLE_HOUSEHOLD_DATA,
    SAMPLE_DB_ROW,
    mock_database,
    mock_hash_object,
)

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
        mock_database.query().fetchone.return_value = SAMPLE_DB_ROW

        service.update_household(
            "us",
            1,
            SAMPLE_HOUSEHOLD_DATA["data"],
            SAMPLE_HOUSEHOLD_DATA["label"],
        )

        assert mock_hash_object.called
        mock_database.query.assert_any_call(
            "UPDATE household SET household_json = ?, household_hash = ?, label = ?, api_version = ? WHERE id = ?",
            (
                json.dumps(SAMPLE_HOUSEHOLD_DATA["data"]),
                "some-hash",
                SAMPLE_HOUSEHOLD_DATA["label"],
                COUNTRY_PACKAGE_VERSIONS.get("us"),
                1,
            ),
        )

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
