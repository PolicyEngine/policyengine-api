import pytest

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