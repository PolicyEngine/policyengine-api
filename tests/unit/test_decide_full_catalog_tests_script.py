"""Tests for .github/scripts/decide_full_catalog_tests.sh.

The script decides whether the full-catalog job in
.github/workflows/v2-integration-check.yml runs its tests: on a pull request or
a push only when the change touches a path their outcome depends on, and on a
scheduled or manual run always. Each test builds a temporary git repository
with a master branch and a change on top of it.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest

from tests.unit.cloud_run_deploy_support import REPO

if TYPE_CHECKING:
    from pathlib import Path

DECIDE_SCRIPT = REPO / ".github/scripts/decide_full_catalog_tests.sh"
RUN = "run_full_catalog_tests=true\n"
SKIP = "run_full_catalog_tests=false\n"
FULL_CATALOG_PATHS = [
    "uv.lock",
    "pyproject.toml",
    "policyengine_api/data/v2/catalog/publication.py",
    "policyengine_api/data/v2/catalog/new_module.py",
    "policyengine_api/data/v2/models/metadata.py",
    "migrations/v2/versions/20261030_add_column.py",
    "migrations/v2/env.py",
    "alembic-v2.ini",
    "tests/fixtures/installed_catalog.py",
    "tests/integration/test_v2_catalog_installed.py",
    "tests/integration/test_v2_catalog_publication_qualification.py",
    ".github/workflows/v2-integration-check.yml",
    ".github/scripts/decide_full_catalog_tests.sh",
]
OTHER_PATHS = [
    "README.md",
    "policyengine_api/data/v2/models/policies.py",
    "policyengine_api/data/v2/settings.py",
    "migrations/v1/versions/20261030_add_column.py",
    "alembic-v1.ini",
    "tests/fixtures/v2_catalog.py",
    "tests/integration/test_v2_catalog_publication.py",
    "tests/unit/v2/test_catalog_extraction.py",
    ".github/workflows/pr.yml",
    "docs/policyengine_api/data/v2/catalog/notes.md",
]


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


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=_git_environment(),
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _write(repository: Path, relative_path: str, text: str = "changed\n") -> None:
    file_path = repository / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(text, encoding="utf-8")


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "--allow-empty", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Return a repository whose master holds every path the decision lists."""
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet", "--initial-branch=master")
    for relative_path in [*FULL_CATALOG_PATHS, *OTHER_PATHS]:
        _write(repository, relative_path, "original\n")
    _commit(repository, "Master")
    _git(repository, "checkout", "--quiet", "-b", "change")
    return repository


def _decide(
    repository: Path,
    *,
    event_name: str | None,
    base_revision: str | None,
    output_path: Path | None,
) -> subprocess.CompletedProcess[str]:
    environment = _git_environment()
    for name in ("EVENT_NAME", "BASE_SHA", "GITHUB_OUTPUT"):
        environment.pop(name, None)
    if event_name is not None:
        environment["EVENT_NAME"] = event_name
    if base_revision is not None:
        environment["BASE_SHA"] = base_revision
    if output_path is not None:
        environment["GITHUB_OUTPUT"] = str(output_path)
    return subprocess.run(
        ["bash", str(DECIDE_SCRIPT)],
        cwd=repository,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _decision(
    repository: Path, *, event_name: str, base_revision: str | None
) -> tuple[str, str]:
    """Return the step output the script wrote and what it printed."""
    output_path = repository.parent / "github-output"
    output_path.write_text("", encoding="utf-8")
    result = _decide(
        repository,
        event_name=event_name,
        base_revision=base_revision,
        output_path=output_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output_path.read_text(encoding="utf-8"), result.stdout


@pytest.mark.parametrize("changed_path", FULL_CATALOG_PATHS)
def test_a_pull_request_that_changes_a_full_catalog_path_runs_the_tests(
    repository: Path, changed_path: str
) -> None:
    master = _git(repository, "rev-parse", "master")
    _write(repository, changed_path)
    _commit(repository, f"Change {changed_path}")

    output, printed = _decision(
        repository, event_name="pull_request", base_revision=master
    )

    assert output == RUN
    assert f"  {changed_path}\n" in printed


@pytest.mark.parametrize("changed_path", OTHER_PATHS)
def test_a_pull_request_that_changes_another_path_skips_the_tests(
    repository: Path, changed_path: str
) -> None:
    master = _git(repository, "rev-parse", "master")
    _write(repository, changed_path)
    _commit(repository, f"Change {changed_path}")

    output, printed = _decision(
        repository, event_name="pull_request", base_revision=master
    )

    assert output == SKIP
    assert "touches none of the paths" in printed


def test_moving_a_catalog_module_elsewhere_runs_the_tests(repository: Path) -> None:
    master = _git(repository, "rev-parse", "master")
    _git(
        repository,
        "mv",
        "policyengine_api/data/v2/catalog/publication.py",
        "policyengine_api/data/v2/publication.py",
    )
    _commit(repository, "Move the publication module")

    output, printed = _decision(
        repository, event_name="pull_request", base_revision=master
    )

    assert output == RUN
    assert "  policyengine_api/data/v2/catalog/publication.py\n" in printed


def test_deleting_a_full_catalog_test_runs_the_tests(repository: Path) -> None:
    master = _git(repository, "rev-parse", "master")
    (repository / "tests/integration/test_v2_catalog_installed.py").unlink()
    _commit(repository, "Delete the installed catalog test")

    output, _printed = _decision(
        repository, event_name="pull_request", base_revision=master
    )

    assert output == RUN


def test_a_test_merge_commit_ignores_what_the_base_branch_changed(
    repository: Path,
) -> None:
    # GitHub checks a pull request out at a merge commit whose first parent is
    # the base branch's head; the base branch changed uv.lock after the pull
    # request branched, and the pull request changed only the README.
    _write(repository, "README.md")
    pull_request_head = _commit(repository, "Change the README")
    _git(repository, "checkout", "--quiet", "master")
    _write(repository, "uv.lock")
    base_head = _commit(repository, "Update uv.lock on master")
    _git(repository, "checkout", "--quiet", "--detach", base_head)
    _git(repository, "merge", "--quiet", "--no-ff", "-m", "Merge", pull_request_head)

    output, _printed = _decision(
        repository, event_name="pull_request", base_revision=base_head
    )

    assert output == SKIP


def test_a_push_compares_with_the_commit_before_it(repository: Path) -> None:
    _write(repository, "uv.lock")
    before = _commit(repository, "Update uv.lock")
    _write(repository, "README.md")
    _commit(repository, "Change the README")

    output, _printed = _decision(repository, event_name="push", base_revision=before)

    assert output == SKIP


@pytest.mark.parametrize("event_name", ["schedule", "workflow_dispatch"])
def test_a_scheduled_or_manual_run_always_runs_the_tests(
    repository: Path, event_name: str
) -> None:
    output, printed = _decision(repository, event_name=event_name, base_revision="")

    assert output == RUN
    assert f"A {event_name} run runs the full-catalog tests" in printed


@pytest.mark.parametrize("base_revision", [None, "", "0" * 40])
def test_a_change_with_no_commit_to_compare_with_runs_the_tests(
    repository: Path, base_revision: str | None
) -> None:
    output, printed = _decision(
        repository, event_name="push", base_revision=base_revision
    )

    assert output == RUN
    assert "::notice::There is no commit to compare with" in printed


def test_a_base_commit_missing_from_the_clone_runs_the_tests(
    repository: Path,
) -> None:
    missing_commit = "1" * 40

    output, printed = _decision(
        repository, event_name="push", base_revision=missing_commit
    )

    assert output == RUN
    assert f"::notice::{missing_commit} is not in this clone's history" in printed


def test_the_event_name_is_required(repository: Path, tmp_path: Path) -> None:
    result = _decide(
        repository,
        event_name=None,
        base_revision="master",
        output_path=tmp_path / "github-output",
    )

    assert result.returncode != 0
    assert "EVENT_NAME is required" in result.stderr


def test_the_step_output_file_is_required(repository: Path) -> None:
    result = _decide(
        repository,
        event_name="pull_request",
        base_revision="master",
        output_path=None,
    )

    assert result.returncode != 0
    assert "GITHUB_OUTPUT is required" in result.stderr
