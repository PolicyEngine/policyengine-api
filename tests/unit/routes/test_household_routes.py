import pytest
import json
from unittest.mock import MagicMock
from sqlalchemy.engine.row import LegacyRow

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS

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

        updated_household = {
            "people": {"person1": {"age": 31, "income": 55000}}
        }

        updated_data = {
            "data": updated_household,
            "label": SAMPLE_HOUSEHOLD_DATA["label"],
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
                SAMPLE_HOUSEHOLD_DATA["label"],
                COUNTRY_PACKAGE_VERSIONS.get("us"),
                1,
            ),
        )

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