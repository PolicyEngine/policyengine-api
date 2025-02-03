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
            print(f"Failed response: {response.text}")  # Log error for debugging

        assert response.status_code == 200, f"Invalid HUGGING_FACE_TOKEN: {response.text}"

    
    @pytest.mark.xfail(
        condition=lambda: os.getenv("FLASK_DEBUG") == "1",
        reason="Skipping in debug mode",
        run=False,
    )

    def test_github_microdata_auth_token(self):

        """Test if POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN has access to the organization's repositories."""
       
        token = os.getenv("POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN")
        org = os.getenv("GITHUB_ORG")  # Organization name must be set as an env variable
        pat_id = os.getenv("GITHUB_PAT_ID")  # Fine-grained personal access token ID

        if not token or not org or not pat_id:
            pytest.skip("Skipping test: Required GitHub credentials not set")

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        repo_url = f"https://api.github.com/orgs/{org}/personal-access-tokens/{pat_id}/repositories"
        response = requests.get(repo_url, headers=headers, timeout=5)

        if response.status_code != 200:
            print(f"Failed response: {response.text}")  # Log error for debugging

        assert response.status_code == 200, f"Failed to list repositories: {response.text}"

        repos = response.json().get("repositories", [])
        if not repos:
            pytest.fail("Token does not have access to any repositories")
    
