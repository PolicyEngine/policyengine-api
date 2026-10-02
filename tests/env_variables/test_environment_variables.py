import os
import pytest
import requests

HUGGING_FACE_API_URL = "https://huggingface.co/api/whoami-v2"
HUGGING_FACE_UK_DATA_MODEL_URL = (
    "https://huggingface.co/api/models/policyengine/policyengine-uk-data-private"
)
HUGGING_FACE_UK_POPULATION_DATASET_URL = (
    "https://huggingface.co/api/datasets/policyengine/populace-uk-private"
)
EXPECTED_HUGGING_FACE_TOKEN_NAME = "pe-uk-private-hf-read-token"
GITHUB_API_URL = "https://api.github.com/user"


def do_not_run_in_debug():
    return os.getenv("FLASK_DEBUG") == "1"


class TestEnvironmentVariables:
    """Tests for expiring environment variables."""

    @pytest.mark.skipif(
        do_not_run_in_debug(),
        reason="Skipping in debug mode",
    )
    def test_hugging_face_token(self):
        """Test if HUGGING_FACE_TOKEN is valid by querying Hugging Face API."""

        token = os.getenv("HUGGING_FACE_TOKEN")
        assert token is not None, "HUGGING_FACE_TOKEN is not set"

        token_validation_response = requests.get(
            HUGGING_FACE_API_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )

        assert token_validation_response.status_code == 200, (
            f"Invalid HUGGING_FACE_TOKEN: {token_validation_response.text}"
        )
        token_details = token_validation_response.json()["auth"]["accessToken"]
        assert token_details["displayName"] == EXPECTED_HUGGING_FACE_TOKEN_NAME
        assert token_details["role"] == "fineGrained"
        fine_grained = token_details["fineGrained"]
        granted_permissions = set(fine_grained.get("global", []))
        granted_permissions.update(
            permission
            for scope in fine_grained["scoped"]
            for permission in scope["permissions"]
        )
        assert "repo.content.read" in granted_permissions
        assert not any("write" in permission for permission in granted_permissions)

        headers = {"Authorization": f"Bearer {token}"}
        uk_data_response = requests.get(
            HUGGING_FACE_UK_DATA_MODEL_URL,
            headers=headers,
            timeout=10,
        )
        assert uk_data_response.status_code == 200, (
            "The API runtime token cannot read "
            "policyengine/policyengine-uk-data-private: "
            f"{uk_data_response.text}"
        )
        uk_data_files = {
            sibling["rfilename"] for sibling in uk_data_response.json()["siblings"]
        }
        assert "local_authority_weights.h5" in uk_data_files

        populace_response = requests.get(
            HUGGING_FACE_UK_POPULATION_DATASET_URL,
            headers=headers,
            timeout=10,
        )
        assert populace_response.status_code == 200, (
            "The shared API and simulation runtime token cannot read "
            f"policyengine/populace-uk-private: {populace_response.text}"
        )
        populace_files = {
            sibling["rfilename"] for sibling in populace_response.json()["siblings"]
        }
        assert "populace_uk_2023.h5" in populace_files

    @pytest.mark.skipif(
        do_not_run_in_debug(),
        reason="Skipping in debug mode",
    )
    def test_github_microdata_auth_token(self):
        """Test if POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN is valid by querying GitHub user API."""

        token = os.getenv("POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN")
        assert token is not None, "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN is not set"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        token_validation_response = requests.get(
            GITHUB_API_URL,
            headers=headers,
            timeout=5,
        )

        assert token_validation_response.status_code == 200, (
            f"Invalid POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN: {token_validation_response.text}"
        )

        token_user_details = token_validation_response.json()
        assert "login" in token_user_details, (
            "Token is valid but did not return expected user details"
        )
