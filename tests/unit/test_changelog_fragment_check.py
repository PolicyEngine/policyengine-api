"""Tests for the changelog fragment PR check (rule api.process.changelog-fragment).

``.github/scripts/check_changelog_fragment.sh`` compares the checked-out
commit with the pull request's base commit (``BASE_SHA``) and passes the
changes in changelog.d/ to ``.github/changelog_fragments.py``. Each test builds
a temporary git repository with a master branch, holding one pending fragment
as master does between releases, and a pull request branch.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import yaml

from tests.unit.changelog_fragment_support import REPO, changelog_fragments

if TYPE_CHECKING:
    from pathlib import Path

fragments_module = changelog_fragments()

CHECK_SCRIPT = REPO / ".github/scripts/check_changelog_fragment.sh"
PR_WORKFLOW = REPO / ".github/workflows/pr.yml"
PENDING_FRAGMENT = "changelog.d/telemetry-rank-cause-copies.fixed.md"
OWN_FRAGMENT = "changelog.d/4114.fixed.md"
PULL_REQUEST_4084_FRAGMENT = "changelog.d/added/4083.md"
LOWER_FRAGMENT = "changelog.d/4200.added.md"
ALREADY_RELEASED = (
    f"::error file={LOWER_FRAGMENT}::{LOWER_FRAGMENT} is a fragment the base "
    "branch has already released: a release removed it after this branch left "
    "the base branch, so merging would publish it again. This happens when a "
    "pull request lower in a stack merged; rebase this branch onto the base "
    "branch without that pull request's commits. If it is a new note that "
    "reuses the name, rename it.\n"
)
FRAGMENT_TEXT = "Report when the deployed version went live.\n"
NO_OWN_FRAGMENT = "::error::This pull request adds no changelog fragment of its own."
ON_THE_BASE_BRANCH = (
    "It is already on the base branch, so the next release fails until a pull "
    "request fixes it."
)


def _git_environment() -> dict[str, str]:
    """Return an environment that ignores the user's and system git settings."""
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }


def _git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=directory,
        env=_git_environment(),
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _write(repository: Path, relative_path: str, text: str = FRAGMENT_TEXT) -> None:
    file_path = repository / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(text, encoding="utf-8")


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "--allow-empty", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Return a repository on a pull request branch cut from master.

    Master holds the repository's pyproject.toml, changelog.d/.gitkeep and one
    pending fragment from an earlier pull request.
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet", "--initial-branch=master")
    (repository / "pyproject.toml").write_text(
        (REPO / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _write(repository, "changelog.d/.gitkeep", "")
    _write(repository, PENDING_FRAGMENT, "Copy each telemetry rank cause.\n")
    _write(repository, "README.md", "The Public API.\n")
    _commit(repository, "Master with a pending fragment")
    _git(repository, "checkout", "--quiet", "-b", "pull-request")
    return repository


def _master(repository: Path) -> str:
    return _git(repository, "rev-parse", "master")


def _run_check(
    repository: Path, base_revision: str | None
) -> subprocess.CompletedProcess[str]:
    environment = {**_git_environment(), "PYTHON": sys.executable}
    environment.pop("BASE_SHA", None)
    if base_revision is not None:
        environment["BASE_SHA"] = base_revision
    return subprocess.run(
        ["bash", str(CHECK_SCRIPT)],
        cwd=repository,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _merge_into_master(repository: Path) -> str:
    """Check out a merge of the pull request into master, as GitHub's checkout does.

    GitHub checks out refs/pull/<number>/merge, a merge commit whose first parent
    is the base commit and whose second is the pull request's head.
    """
    _git(repository, "checkout", "--quiet", "--detach", "master")
    _git(
        repository,
        "merge",
        "--quiet",
        "--no-ff",
        "-m",
        "Merge pull-request into master",
        "pull-request",
    )
    return _git(repository, "rev-parse", "HEAD")


def test_a_pull_request_with_no_fragment_fails_while_master_has_a_pending_one(
    repository: Path,
):
    _write(repository, "README.md", "The Public API, changed.\n")
    _commit(repository, "Change the README")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert NO_OWN_FRAGMENT in result.stdout
    assert (
        "Fragments already on the base branch belong to the pull requests that "
        f"added them: {PENDING_FRAGMENT}." in result.stdout
    )
    assert "Add a file changelog.d/<name>.<type>.md" in result.stdout


def test_a_pull_request_that_only_edits_a_pending_fragment_fails(repository: Path):
    _write(repository, PENDING_FRAGMENT, "Copy each telemetry rank cause, edited.\n")
    _commit(repository, "Edit the pending fragment")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert NO_OWN_FRAGMENT in result.stdout


def test_a_pull_request_that_only_deletes_a_pending_fragment_fails(repository: Path):
    (repository / PENDING_FRAGMENT).unlink()
    _commit(repository, "Delete the pending fragment")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert NO_OWN_FRAGMENT in result.stdout


def test_renaming_a_pending_fragment_does_not_add_one(repository: Path):
    _git(repository, "mv", PENDING_FRAGMENT, "changelog.d/renamed.fixed.md")
    _commit(repository, "Rename the pending fragment")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert NO_OWN_FRAGMENT in result.stdout
    assert (
        f"Renaming a fragment that is already on the base branch "
        f"({PENDING_FRAGMENT} to changelog.d/renamed.fixed.md) doesn't add one."
        in result.stdout
    )


def test_a_pull_request_that_adds_a_fragment_passes(repository: Path):
    _write(repository, OWN_FRAGMENT)
    _commit(repository, "Add a fragment")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 0, result.stdout
    assert result.stdout == (
        f"This pull request adds 1 changelog fragment: {OWN_FRAGMENT} (fixed).\n"
    )


def test_a_pull_request_that_adds_a_fragment_and_edits_a_pending_one_passes(
    repository: Path,
):
    _write(repository, OWN_FRAGMENT)
    _write(repository, PENDING_FRAGMENT, "Copy each telemetry rank cause, edited.\n")
    _commit(repository, "Add a fragment and edit the pending one")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 0, result.stdout


def test_moving_a_file_the_release_could_not_read_into_place_adds_a_fragment(
    repository: Path,
):
    _git(repository, "checkout", "--quiet", "master")
    _write(repository, PULL_REQUEST_4084_FRAGMENT)
    _commit(repository, "Master with #4084's fragment")
    _git(repository, "checkout", "--quiet", "-B", "pull-request")
    _git(
        repository,
        "mv",
        PULL_REQUEST_4084_FRAGMENT,
        "changelog.d/report-live-since.added.md",
    )
    _commit(repository, "Move #4084's fragment to the name the release reads")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 0, result.stdout
    assert "changelog.d/report-live-since.added.md (added)" in result.stdout


def test_pull_request_4084s_fragment_fails_and_says_where_it_belongs(
    repository: Path,
):
    _write(repository, PULL_REQUEST_4084_FRAGMENT)
    _commit(repository, "Add a fragment in a folder")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert (
        f"::error file={PULL_REQUEST_4084_FRAGMENT}::{PULL_REQUEST_4084_FRAGMENT} "
        "is in a folder inside changelog.d/. The release reads only files "
        "directly in changelog.d/ and stops at anything else there. Move it to "
        "changelog.d/4083.added.md.\n" in result.stdout
    )
    assert NO_OWN_FRAGMENT in result.stdout


@pytest.mark.parametrize(
    ("relative_path", "text", "expected_problem"),
    [
        ("changelog.d/4114.feature.md", FRAGMENT_TEXT, 'has the type "feature"'),
        ("changelog.d/4114.md", FRAGMENT_TEXT, "is not named <name>.<type>.md"),
        ("changelog.d/4114.fixed.md", "", "is empty."),
        ("changelog.d/4114.fixed.md", "  \n\n", "holds only whitespace."),
    ],
    ids=["unknown-type", "no-type", "empty", "whitespace-only"],
)
def test_a_pull_request_whose_only_fragment_is_unreadable_fails(
    repository: Path, relative_path: str, text: str, expected_problem: str
):
    _write(repository, relative_path, text)
    _commit(repository, "Add an unreadable fragment")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert f"::error file={relative_path}::{relative_path} " in result.stdout
    assert expected_problem in result.stdout
    assert NO_OWN_FRAGMENT in result.stdout


def test_an_unreadable_file_beside_a_valid_fragment_fails(repository: Path):
    _write(repository, OWN_FRAGMENT)
    _write(repository, "changelog.d/notes.md", "Notes.\n")
    _commit(repository, "Add a fragment and a notes file")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert "::error file=changelog.d/notes.md::" in result.stdout
    assert NO_OWN_FRAGMENT not in result.stdout


def test_emptying_a_pending_fragment_fails_even_with_a_fragment_of_its_own(
    repository: Path,
):
    _write(repository, OWN_FRAGMENT)
    _write(repository, PENDING_FRAGMENT, "")
    _commit(repository, "Add a fragment and empty the pending one")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert f"::error file={PENDING_FRAGMENT}::{PENDING_FRAGMENT} is empty." in (
        result.stdout
    )
    assert ON_THE_BASE_BRANCH not in result.stdout


def test_a_submodule_in_changelog_d_fails(repository: Path):
    _write(repository, OWN_FRAGMENT)
    _git(
        repository,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{_master(repository)},changelog.d/vendored.added.md",
    )
    _git(repository, "add", OWN_FRAGMENT)
    # Commit the index as it stands: git add --all would stage the submodule's
    # removal, since the working tree has no folder for it.
    _git(repository, "commit", "--quiet", "-m", "Add a fragment and a submodule")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert (
        "::error file=changelog.d/vendored.added.md::changelog.d/vendored.added.md "
        "is an empty folder or a submodule inside changelog.d/." in result.stdout
    )


def test_an_unreadable_file_already_on_master_fails_and_says_so(repository: Path):
    _git(repository, "checkout", "--quiet", "master")
    _write(repository, PULL_REQUEST_4084_FRAGMENT)
    _commit(repository, "Master with #4084's fragment")
    _git(repository, "checkout", "--quiet", "-B", "pull-request")
    _write(repository, OWN_FRAGMENT)
    _commit(repository, "Add a fragment")

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert f"Move it to changelog.d/4083.added.md. {ON_THE_BASE_BRANCH}" in (
        result.stdout
    )


def test_on_the_merge_commit_only_the_pull_requests_own_changes_count(
    repository: Path,
):
    _write(repository, "README.md", "The Public API, changed.\n")
    _commit(repository, "Change the README")
    _git(repository, "checkout", "--quiet", "master")
    _write(repository, "changelog.d/4110.added.md")
    _commit(repository, "Merge another pull request, with its fragment")
    _merge_into_master(repository)

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert NO_OWN_FRAGMENT in result.stdout
    assert "changelog.d/4110.added.md" in result.stdout


def test_on_the_merge_commit_the_pull_requests_fragment_counts(repository: Path):
    _write(repository, OWN_FRAGMENT)
    _commit(repository, "Add a fragment")
    _git(repository, "checkout", "--quiet", "master")
    _write(repository, "changelog.d/4110.added.md")
    _commit(repository, "Merge another pull request, with its fragment")
    merge_commit = _merge_into_master(repository)

    result = _run_check(repository, _master(repository))

    assert _git(repository, "rev-parse", "HEAD^1") == _master(repository)
    assert _git(repository, "rev-parse", "HEAD") == merge_commit
    assert result.returncode == 0, result.stdout
    assert result.stdout == (
        f"This pull request adds 1 changelog fragment: {OWN_FRAGMENT} (fixed).\n"
    )


def test_a_pull_request_stacked_on_another_needs_its_own_fragment(
    repository: Path,
):
    _write(repository, OWN_FRAGMENT)
    lower_head = _commit(repository, "The lower pull request, with its fragment")
    _git(repository, "checkout", "--quiet", "-b", "upper-pull-request")
    _write(repository, "README.md", "The Public API, changed.\n")
    _commit(repository, "The upper pull request, without a fragment")

    result = _run_check(repository, lower_head)

    assert result.returncode == 1, result.stdout
    assert NO_OWN_FRAGMENT in result.stdout


def _squash_merge_and_release_the_lower_pull_request(repository: Path) -> None:
    """Leave the pull request branch on top of a lower one that merged and released.

    The lower pull request added LOWER_FRAGMENT in two commits. Master
    squash-merged it, then the release commit removed every fragment. The pull
    request branch, cut from the lower one and not rebased, still holds the
    lower pull request's commits.
    """
    _git(repository, "checkout", "--quiet", "-B", "lower", "master")
    _write(repository, "code.txt", "The lower change.\n")
    _write(repository, LOWER_FRAGMENT, "Lower change.\n")
    _commit(repository, "The lower pull request")
    _write(repository, LOWER_FRAGMENT, "Lower change, reworded.\n")
    _commit(repository, "Reword the lower pull request's fragment")
    _git(repository, "checkout", "--quiet", "-B", "pull-request")
    _write(repository, "upper.txt", "The upper change.\n")
    _commit(repository, "The upper pull request, without a fragment")
    _git(repository, "checkout", "--quiet", "master")
    _git(repository, "merge", "--quiet", "--squash", "lower")
    _commit(repository, "Squash-merge the lower pull request")
    _git(repository, "rm", "--quiet", PENDING_FRAGMENT, LOWER_FRAGMENT)
    _commit(repository, "Update PolicyEngine API")
    _git(repository, "checkout", "--quiet", "pull-request")


def test_on_the_merge_commit_a_fragment_already_released_does_not_count(
    repository: Path,
):
    _squash_merge_and_release_the_lower_pull_request(repository)
    _merge_into_master(repository)

    result = _run_check(repository, _master(repository))

    assert (repository / LOWER_FRAGMENT).is_file()
    assert result.returncode == 1, result.stdout
    assert ALREADY_RELEASED in result.stdout
    assert NO_OWN_FRAGMENT in result.stdout


def test_at_the_pull_requests_head_a_fragment_already_released_does_not_count(
    repository: Path,
):
    _squash_merge_and_release_the_lower_pull_request(repository)

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert ALREADY_RELEASED in result.stdout
    assert NO_OWN_FRAGMENT in result.stdout


def test_a_released_fragment_beside_the_pull_requests_own_still_fails(
    repository: Path,
):
    _squash_merge_and_release_the_lower_pull_request(repository)
    _write(repository, OWN_FRAGMENT)
    _commit(repository, "Add the upper pull request's fragment")
    _merge_into_master(repository)

    result = _run_check(repository, _master(repository))

    assert result.returncode == 1, result.stdout
    assert result.stdout == ALREADY_RELEASED


def test_a_shallow_clone_fails_and_says_to_fetch_the_history(
    repository: Path, tmp_path: Path
):
    _write(repository, OWN_FRAGMENT)
    _commit(repository, "Add a fragment")
    _merge_into_master(repository)
    shallow_clone = tmp_path / "shallow"
    _git(
        tmp_path,
        "clone",
        "--quiet",
        "--depth=1",
        f"file://{repository}",
        str(shallow_clone),
    )

    result = _run_check(shallow_clone, _master(repository))

    assert result.returncode == 1, result.stdout
    assert result.stdout.startswith("::error::This clone is shallow")
    assert "fetch-depth: 0" in result.stdout


def test_a_base_commit_the_clone_lacks_fails(repository: Path):
    _write(repository, OWN_FRAGMENT)
    _commit(repository, "Add a fragment")

    result = _run_check(repository, "0" * 40)

    assert result.returncode == 1, result.stdout
    assert f"::error::Could not find a common ancestor of {'0' * 40} and HEAD" in (
        result.stdout
    )


def test_the_base_commit_is_required(repository: Path):
    result = _run_check(repository, None)

    assert result.returncode != 0
    assert "BASE_SHA is required" in result.stderr


@pytest.mark.parametrize(
    ("name_status", "expected_added_paths"),
    [
        (b"A\0changelog.d/a.added.md\0", {"changelog.d/a.added.md"}),
        (b"M\0changelog.d/a.added.md\0D\0changelog.d/b.fixed.md\0", set()),
        (b"R100\0changelog.d/a.added.md\0changelog.d/b.added.md\0", set()),
        (
            b"R087\0changelog.d/added/4083.md\0changelog.d/4083.added.md\0",
            {"changelog.d/4083.added.md"},
        ),
        (
            b"C100\0changelog.d/a.added.md\0changelog.d/b.added.md\0",
            {"changelog.d/b.added.md"},
        ),
        (b"T\0changelog.d/a.added.md\0", set()),
    ],
    ids=[
        "added",
        "modified-and-deleted",
        "renamed-fragment",
        "renamed-unreadable-file",
        "copied",
        "type-changed",
    ],
)
def test_the_paths_a_pull_request_adds(
    name_status: bytes, expected_added_paths: set[str]
):
    definition = fragments_module.FragmentDefinition.load(REPO)
    changes = fragments_module.parse_name_status(name_status)

    assert definition.added_paths(changes) == expected_added_paths


def test_the_released_paths_are_read_from_git_logs_nul_separated_names():
    assert fragments_module.parse_paths(
        b"changelog.d/a.added.md\0\nchangelog.d/b.fixed.md\0\0"
    ) == {"changelog.d/a.added.md", "changelog.d/b.fixed.md"}


def test_name_status_output_that_ends_mid_record_is_refused():
    with pytest.raises(ValueError, match="ends in the middle of a change"):
        fragments_module.parse_name_status(b"R100\0changelog.d/a.added.md\0")


def test_annotation_properties_escape_the_characters_the_runner_reads():
    assert fragments_module.annotation_property("changelog.d/a,b:c%.md") == (
        "changelog.d/a%2Cb%3Ac%25.md"
    )
    assert fragments_module.annotation_message("line one\nline two 100%") == (
        "line one%0Aline two 100%25"
    )


def _check_changelog_job() -> dict:
    workflow = yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["check-changelog"]


def test_the_job_checks_out_the_history_and_passes_the_base_commit():
    job = _check_changelog_job()
    checkout_step, python_step, check_step = job["steps"]

    assert checkout_step["uses"] == "actions/checkout@v4"
    assert checkout_step["with"] == {"fetch-depth": 0}
    assert python_step["uses"] == "actions/setup-python@v5"
    assert python_step["with"] == {"python-version": "3.12"}
    assert check_step["env"] == {
        "BASE_SHA": "${{ github.event.pull_request.base.sha }}"
    }
    assert check_step["run"] == "bash .github/scripts/check_changelog_fragment.sh"
    assert job["permissions"] == {"contents": "read"}


def test_the_job_keeps_the_stack_condition_and_is_needed_by_ci_complete():
    workflow = yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["check-changelog"]

    assert job["if"] == (
        "${{ !github.event.pull_request.stack || "
        "github.event.pull_request.stack.base.ref == "
        "github.event.pull_request.base.ref }}"
    )
    assert "check-changelog" in workflow["jobs"]["ci-complete"]["needs"]
