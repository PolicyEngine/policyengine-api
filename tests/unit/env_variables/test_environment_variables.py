import os
import pytest
import requests


class TestEnvironmentVariables:

    """Tests for expiring environment variables."""

    @pytest.mark.xfail(
        condition=lambda: os.getenv("FLASK_DEBUG") == "1",
        reason="Skipping in debug mode",
        run=False,
    )
    def test_hugging_face_token(self):
        """Test if HUGGING_FACE_TOKEN is valid by querying Hugging Face API."""
        token = os.getenv("HUGGING_FACE_TOKEN")
        if not token:
            pytest.skip("Skipping test: HUGGING_FACE_TOKEN is not set")

        response = requests.get(
            "https://huggingface.co/api/whoami",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )

        if response.status_code != 200:
            print(
                f"Failed response: {response.text}"
            )  # Log error for debugging

        assert (
            response.status_code == 200
        ), f"Invalid HUGGING_FACE_TOKEN: {response.text}"

    @pytest.mark.xfail(
        condition=lambda: os.getenv("FLASK_DEBUG") == "1",
        reason="Skipping in debug mode",
        run=False,
    )
    def test_github_microdata_auth_token(self):
        """Test if POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN is valid by querying GitHub user API."""
        token = os.getenv("POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN")
        if not token:
            pytest.skip(
                "Skipping test: POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN is not set"
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        response = requests.get(
            "https://api.github.com/user", headers=headers, timeout=5
        )

        if response.status_code != 200:
            print(
                f"Failed response: {response.text}"
            )  # Log error for debugging

        assert (
            response.status_code == 200
        ), f"Invalid POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN: {response.text}"

        user_data = response.json()
        if "login" not in user_data:
            pytest.fail(
                "Token is valid but did not return expected user details"
            )
