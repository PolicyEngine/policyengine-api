import os
from urllib.parse import quote

import pytest
import requests

from policyengine_api.constants import get_bundle_data_release

HUGGING_FACE_API_URL = "https://huggingface.co/api/whoami-v2"
HUGGING_FACE_UK_DATA_MODEL_URL = (
    "https://huggingface.co/api/models/policyengine/policyengine-uk-data-private"
)
HUGGING_FACE_REPOSITORY_API_URL = "https://huggingface.co/api"
HUGGING_FACE_REPOSITORY_TYPE_PATHS = {"model": "models", "dataset": "datasets"}
EXPECTED_HUGGING_FACE_TOKEN_NAME = "pe-uk-private-hf-read-token"
GITHUB_API_URL = "https://api.github.com/user"


def do_not_run_in_debug():
    return os.getenv("FLASK_DEBUG") == "1"


def uk_default_dataset_location() -> tuple[str, str, str, str]:
    """Locate the bundle's default UK dataset: repository type and ID, path, revision.

    The default dataset is the national file UK simulations load when no
    region-specific dataset applies. The location is resolved as the
    ``policyengine`` package resolves it: a dataset entry without its own
    repository, repository type or revision takes the data package's. The
    bundled manifest is read without importing that package, whose import builds
    both country models and contacts Hugging Face.
    """
    release = get_bundle_data_release("uk")
    default_dataset = release.get("default_dataset")
    dataset_entry = release.get("datasets", {}).get(default_dataset)
    assert dataset_entry is not None, (
        f"The bundle has no location for its default UK dataset {default_dataset}"
    )
    data_package = release["data_package"]
    return (
        dataset_entry.get("repo_type") or data_package.get("repo_type") or "model",
        dataset_entry.get("repo_id") or data_package["repo_id"],
        dataset_entry["path"],
        dataset_entry.get("revision")
        or data_package.get("release_manifest_revision")
        or data_package["version"],
    )


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

        # Hugging Face read permission covers a whole repository, so listing the
        # files at the pinned revision checks the credential's access and that
        # the pinned file exists at that revision.
        repository_type, repository_id, dataset_path, dataset_revision = (
            uk_default_dataset_location()
        )
        dataset_response = requests.get(
            f"{HUGGING_FACE_REPOSITORY_API_URL}"
            f"/{HUGGING_FACE_REPOSITORY_TYPE_PATHS[repository_type]}/{repository_id}"
            f"/revision/{quote(dataset_revision, safe='')}",
            headers=headers,
            timeout=10,
        )
        assert dataset_response.status_code == 200, (
            "The shared API and simulation runtime token cannot read "
            f"{repository_type} repository {repository_id} "
            f"at revision {dataset_revision}: {dataset_response.text}"
        )
        dataset_files = {
            sibling["rfilename"] for sibling in dataset_response.json()["siblings"]
        }
        assert dataset_path in dataset_files, (
            f"{repository_id} at revision {dataset_revision} has no {dataset_path}"
        )

    @pytest.mark.skipif(
        do_not_run_in_debug(),
        reason="Skipping in debug mode",
    )
    def test_github_microdata_auth_token(self):
        """Check POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN with the GitHub user API."""
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
            "Invalid POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN: "
            f"{token_validation_response.text}"
        )

        token_user_details = token_validation_response.json()
        assert "login" in token_user_details, (
            "Token is valid but did not return expected user details"
        )
