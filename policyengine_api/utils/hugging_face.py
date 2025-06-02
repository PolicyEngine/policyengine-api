from huggingface_hub import (
    hf_hub_download,
    model_info,
    ModelInfo,
    HfApi,
)
from huggingface_hub.errors import RepositoryNotFoundError
from getpass import getpass
import os
import warnings
import traceback

with warnings.catch_warnings():
    warnings.simplefilter("ignore")


def get_latest_commit_tag(repo_id, repo_type="model"):
    """
    Get the tag associated with the latest commit in a HF repo.
    Returns the tag name or None if no tag is associated.
    """
    api = HfApi()

    is_repo_private = check_is_repo_private(repo_id)

    authentication_token: str = None
    if is_repo_private:
        authentication_token: str = get_or_prompt_hf_token()

    # Get list of commits
    commits = api.list_repo_commits(
        repo_id=repo_id, repo_type=repo_type, token=authentication_token
    )

    if not commits:
        return None

    latest_commit = commits[0]  # Most recent commit is first

    # Get all tags in the repository
    tags = api.list_repo_refs(
        repo_id=repo_id, repo_type=repo_type, token=authentication_token
    ).tags

    # Find tag that points to the latest commit
    for tag in tags:
        if tag.target_commit == latest_commit.commit_id:
            return tag.ref.replace("refs/tags/", "")

    return None


def check_is_repo_private(repo: str) -> bool:
    """
    Check if a Hugging Face repository is private.

    Args:
        repo (str): The Hugging Face repo name, in format "{org}/{repo}".

    Returns:
        bool: True if the repo is private, False otherwise.
    """
    try:
        fetched_model_info: ModelInfo = model_info(repo)
        return fetched_model_info.private
    except RepositoryNotFoundError:
        return True  # If repo not found, assume it's private
    except Exception as e:
        raise Exception(
            f"Unable to check if repo {repo} is private. The full error is {traceback.format_exc()}"
        )


def download_huggingface_dataset(
    repo: str,
    repo_filename: str,
    version: str = None,
    local_dir: str | None = None,
):
    """
    Download a dataset from the Hugging Face Hub.

    Args:
        repo (str): The Hugging Face repo name, in format "{org}/{repo}".
        repo_filename (str): The filename of the dataset.
        version (str, optional): The version of the dataset. Defaults to None.
        local_dir (str, optional): The local directory to save the dataset to. Defaults to None.
    """
    is_repo_private = check_is_repo_private(repo)

    authentication_token: str = None
    if is_repo_private:
        authentication_token: str = get_or_prompt_hf_token()

    return hf_hub_download(
        repo_id=repo,
        repo_type="model",
        filename=repo_filename,
        revision=version,
        token=authentication_token,
        local_dir=local_dir,
    )


def get_or_prompt_hf_token() -> str:
    """
    Either get the Hugging Face token from the environment,
    or prompt the user for it and store it in the environment.

    Returns:
        str: The Hugging Face token.
    """

    token = os.environ.get("HUGGING_FACE_TOKEN")
    if token is None:
        token = getpass(
            "Enter your Hugging Face token (or set HUGGING_FACE_TOKEN environment variable): "
        )
        # Optionally store in env for subsequent calls in same session
        os.environ["HUGGING_FACE_TOKEN"] = token

    return token
