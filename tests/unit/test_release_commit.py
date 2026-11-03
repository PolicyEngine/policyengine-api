"""Tests for the release commit check: .github/release_commit.py and its script.

A release run (the run for the "Update PolicyEngine API" commit) may skip the
checks its merge run passed only when the release commit changes nothing but
release files, and the merge commit's Push run passed every one of those
checks. ``check_release_commit.sh`` gathers the release commit's changes, the
parent's copies of pyproject.toml and uv.lock, and the parent's Push runs, and
``release_commit.py check`` decides. ``release_commit.py require-checks`` stops
publish-git-tag unless the run skipped the checks for that reason or passed
them itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import yaml

from tests.unit.changelog_fragment_support import REPO, release_commit

if TYPE_CHECKING:
    from pathlib import Path

release_commit_module = release_commit()

CHECK_SCRIPT = REPO / ".github/scripts/check_release_commit.sh"
REPOSITORY = "PolicyEngine/policyengine-api"
MERGE_RUN_URL = "https://github.com/PolicyEngine/policyengine-api/actions/runs/101"
PYPROJECT = """[build-system]
requires = ["hatchling"]

[project]
name = "policyengine-api"
version = "5.14.2"
dependencies = [
    "flask",
]

[tool.example]
version = "1.0.0"

[tool.towncrier]
directory = "changelog.d"

[[tool.towncrier.type]]
directory = "fixed"
name = "Fixed"
showcontent = true
"""
LOCK = """version = 1
revision = 3
requires-python = ">=3.11"

[[package]]
name = "flask"
version = "3.1.1"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "policyengine-api"
version = "5.14.2"
source = { editable = "." }
dependencies = [
    { name = "flask" },
]

[package.metadata]
requires-dist = [{ name = "flask" }]
"""
CHANGELOG = "## [5.14.2] - 2026-10-29\n\n### Fixed\n\n- An earlier fix.\n"
FRAGMENT = "changelog.d/economy-missing-policy.fixed.md"


def _bumped(text: str) -> str:
    return text.replace('version = "5.14.2"', 'version = "5.14.3"')


# --- What the release commit changes ----------------------------------------


def _change(path: str, status: str = "M", mode: str = "100644"):
    old_mode = "000000" if status == "A" else mode
    new_mode = "000000" if status == "D" else mode
    return release_commit_module.FileChange(
        path=path, status=status, old_mode=old_mode, new_mode=new_mode
    )


def _release_files(
    *,
    release_pyproject: str | None = None,
    release_lock: str | None = None,
):
    return release_commit_module.ReleaseFiles(
        parent_pyproject=PYPROJECT,
        release_pyproject=(
            _bumped(PYPROJECT) if release_pyproject is None else release_pyproject
        ),
        parent_lock=LOCK,
        release_lock=_bumped(LOCK) if release_lock is None else release_lock,
    )


RELEASE_CHANGES = [
    _change("CHANGELOG.md"),
    _change(FRAGMENT, status="D"),
    _change("pyproject.toml"),
    _change("uv.lock"),
]


def _problems(changes, files=None) -> list[str]:
    return release_commit_module.release_change_problems(
        changes, files or _release_files(), "changelog.d"
    )


def test_a_release_commit_changes_only_release_files():
    assert _problems(RELEASE_CHANGES) == []


def test_the_project_version_lines_are_found_in_their_own_tables():
    pyproject_lines = PYPROJECT.splitlines()
    lock_lines = LOCK.splitlines()

    pyproject_index = release_commit_module.project_version_index(PYPROJECT)
    lock_index = release_commit_module.locked_project_version_index(
        LOCK, "policyengine-api"
    )

    assert pyproject_lines[pyproject_index] == 'version = "5.14.2"'
    assert pyproject_lines[pyproject_index - 1] == 'name = "policyengine-api"'
    assert lock_lines[lock_index] == 'version = "5.14.2"'
    assert lock_lines[lock_index - 1] == 'name = "policyengine-api"'


def test_any_other_file_is_not_a_release_file():
    changes = [*RELEASE_CHANGES, _change("policyengine_api/api.py")]

    assert _problems(changes) == ["policyengine_api/api.py is not a release file"]


def test_pyproject_may_change_only_the_project_version():
    with_a_dependency = _bumped(PYPROJECT).replace('"flask",', '"flask",\n    "rq",')
    other_version = PYPROJECT.replace('version = "1.0.0"', 'version = "1.0.1"')

    for release_pyproject in (with_a_dependency, other_version):
        files = _release_files(release_pyproject=release_pyproject)
        assert _problems(RELEASE_CHANGES, files) == [
            "pyproject.toml changes more than the [project] version"
        ]


def test_uv_lock_may_change_only_the_projects_own_version():
    other_package = _bumped(LOCK).replace('version = "3.1.1"', 'version = "3.1.2"')
    reresolved = LOCK.replace('version = "3.1.1"', 'version = "3.1.2"')
    added_dependency = _bumped(LOCK).replace(
        '    { name = "flask" },', '    { name = "flask" },\n    { name = "rq" },'
    )

    for release_lock in (other_package, reresolved, added_dependency):
        files = _release_files(release_lock=release_lock)
        assert _problems(RELEASE_CHANGES, files) == [
            "uv.lock changes more than policyengine-api's version"
        ]


def test_release_files_must_stay_edited_regular_files():
    changes = [
        _change("CHANGELOG.md", status="D"),
        _change("pyproject.toml", mode="100755"),
        _change("uv.lock", status="T"),
    ]

    assert _problems(changes) == [
        "CHANGELOG.md is not only edited",
        "pyproject.toml changes more than the [project] version",
        "uv.lock changes more than policyengine-api's version",
    ]


def test_the_release_commit_may_only_remove_fragments():
    changes = [
        _change("changelog.d/4200.fixed.md", status="A"),
        _change("changelog.d/4201.fixed.md"),
        _change("changelog.d/.gitkeep", status="D"),
        _change("changelog.d/fixed/4202.md", status="D"),
    ]

    assert _problems(changes) == [
        "changelog.d/4200.fixed.md is a fragment the release commit does not remove",
        "changelog.d/4201.fixed.md is a fragment the release commit does not remove",
        "changelog.d/.gitkeep is not a release file",
        "changelog.d/fixed/4202.md is not a release file",
    ]


def test_git_diff_raw_output_is_parsed_per_path():
    raw_diff = (
        ":100644 100644 aaaa bbbb M\0CHANGELOG.md\0"
        ":100644 000000 cccc 0000 D\0changelog.d/4200.fixed.md\0"
    )

    assert release_commit_module.parse_raw_diff(raw_diff) == [
        _change("CHANGELOG.md"),
        _change("changelog.d/4200.fixed.md", status="D"),
    ]


# --- Whether the merge run passed the checks ----------------------------------


def _passing_jobs() -> list[dict]:
    return [
        {"name": "Lint", "status": "completed", "conclusion": "success"},
        {"name": "Quality guards", "status": "completed", "conclusion": "success"},
        {
            "name": "Alembic v1 qualification / Alembic MySQL lifecycle",
            "status": "completed",
            "conclusion": "success",
        },
        {
            "name": "Alembic v2 qualification / V2 Postgres migration lifecycle",
            "status": "completed",
            "conclusion": "success",
        },
        {
            "name": (
                "Cross-database integration tests / MySQL, PostgreSQL, and Redis "
                "integration"
            ),
            "status": "completed",
            "conclusion": "success",
        },
        {"name": "Update versioning", "status": "completed", "conclusion": "success"},
    ]


def test_a_merge_run_that_passed_every_check_lets_the_release_run_skip_them():
    run = {"id": 101, "html_url": MERGE_RUN_URL}

    merge_run, problems = release_commit_module.passing_merge_run(
        [run], {101: _passing_jobs()}
    )

    assert merge_run == run
    assert problems == []


@pytest.mark.parametrize(
    ("job_name", "status", "conclusion", "problem"),
    [
        (
            "Quality guards",
            "completed",
            "failure",
            "Quality guards ended completed, failure",
        ),
        ("Lint", "in_progress", None, "Lint ended in_progress, None"),
        ("Lint", "completed", "skipped", "Lint ended completed, skipped"),
    ],
)
def test_a_check_that_did_not_pass_in_the_merge_run_runs_again(
    job_name, status, conclusion, problem
):
    jobs = _passing_jobs()
    for job in jobs:
        if job["name"] == job_name:
            job.update(status=status, conclusion=conclusion)

    merge_run, problems = release_commit_module.passing_merge_run(
        [{"id": 101, "html_url": MERGE_RUN_URL}], {101: jobs}
    )

    assert merge_run is None
    assert problems == [f"Push run {MERGE_RUN_URL}: {problem}"]


def test_a_check_missing_from_the_merge_run_runs_again():
    jobs = [job for job in _passing_jobs() if not job["name"].startswith("Alembic v2")]

    merge_run, problems = release_commit_module.passing_merge_run(
        [{"id": 101, "html_url": MERGE_RUN_URL}], {101: jobs}
    )

    assert merge_run is None
    assert problems == [
        f"Push run {MERGE_RUN_URL}: Alembic v2 qualification did not run"
    ]


def test_a_parent_without_a_push_run_runs_the_checks_again():
    assert release_commit_module.passing_merge_run([], {}) == (
        None,
        ["the parent commit has no Push run"],
    )


def test_the_merge_run_checks_are_push_yml_jobs_with_those_names():
    jobs = yaml.safe_load((REPO / ".github/workflows/push.yml").read_text())["jobs"]

    for job_id, job_name in release_commit_module.MERGE_RUN_CHECKS.items():
        assert jobs[job_id]["name"] == job_name
    # tests/unit/test_release_run_checks.py checks push.yml with copies of these.
    assert tuple(release_commit_module.MERGE_RUN_CHECKS) == (
        "lint",
        "quality-guards",
        "alembic-v1-check",
        "alembic-v2-check",
        "v2-integration-check",
    )
    assert set(release_commit_module.RELEASE_RUN_REQUIRED_CHECKS) == set(
        release_commit_module.MERGE_RUN_CHECKS
    ) - {"quality-guards"}


# --- publish-git-tag's requirement --------------------------------------------


def _job_results(*, checks_passed: str, release_check: str, check_result: str):
    results = {
        "ensure-staging-model-version-aligns-with-sim-api": {
            "result": "success",
            "outputs": {},
        },
        "check-release-commit": {
            "result": release_check,
            "outputs": {
                "merge_run_checks_passed": checks_passed,
                "merge_run_url": MERGE_RUN_URL if checks_passed == "true" else "",
            },
        },
    }
    for job_id in release_commit_module.RELEASE_RUN_REQUIRED_CHECKS:
        results[job_id] = {"result": check_result, "outputs": {}}
    return results


@pytest.mark.parametrize(
    ("checks_passed", "release_check", "check_result", "problems"),
    [
        # The merge run passed the checks on the same code: they were skipped.
        ("true", "success", "skipped", []),
        # The release commit check found a reason to run them, and they passed.
        ("false", "success", "success", []),
        # The release commit check itself failed, and the checks passed.
        ("", "failure", "success", []),
        # Checks that ran must pass, whatever the release commit check said.
        ("true", "success", "failure", ["lint ended failure"]),
        ("false", "success", "failure", ["lint ended failure"]),
        # Checks skipped without the release commit check's say-so stop the tag.
        ("false", "success", "skipped", ["lint ended skipped"]),
        ("true", "failure", "skipped", ["lint ended skipped"]),
    ],
)
def test_publish_git_tag_requires_the_merge_run_or_this_run_to_pass_the_checks(
    checks_passed, release_check, check_result, problems
):
    job_results = _job_results(
        checks_passed=checks_passed,
        release_check=release_check,
        check_result=check_result,
    )
    for job_id in ("alembic-v1-check", "alembic-v2-check", "v2-integration-check"):
        if problems:
            job_results[job_id]["result"] = "success"

    assert release_commit_module.release_check_problems(job_results) == problems


def test_publish_git_tag_must_need_every_required_check():
    job_results = _job_results(
        checks_passed="true", release_check="success", check_result="skipped"
    )
    del job_results["alembic-v1-check"]

    assert release_commit_module.release_check_problems(job_results) == [
        "publish-git-tag does not need alembic-v1-check"
    ]


def _require_checks(job_results: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO / ".github/release_commit.py"), "require-checks"],
        cwd=REPO,
        env={**os.environ, "JOB_RESULTS": json.dumps(job_results)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_require_checks_exits_1_and_names_the_check_that_did_not_pass():
    result = _require_checks(
        _job_results(
            checks_passed="false", release_check="success", check_result="failure"
        )
    )

    assert result.returncode == 1
    assert "::error::lint ended failure" in result.stdout


def test_require_checks_names_the_merge_run_whose_checks_this_run_skipped():
    result = _require_checks(
        _job_results(
            checks_passed="true", release_check="success", check_result="skipped"
        )
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert MERGE_RUN_URL in result.stdout


# --- check_release_commit.sh, end to end ----------------------------------------


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
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(repository: Path, relative_path: str, text: str) -> None:
    path = repository / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _merge_commit_repository(tmp_path: Path) -> tuple[Path, str]:
    """Return a repository whose HEAD is a merge commit with one pending fragment."""
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet", "--initial-branch", "master")
    _write(repository, "pyproject.toml", PYPROJECT)
    _write(repository, "uv.lock", LOCK)
    _write(repository, "CHANGELOG.md", CHANGELOG)
    _write(repository, "changelog.d/.gitkeep", "")
    _write(repository, FRAGMENT, "Return 404 for a missing policy.\n")
    _write(repository, "policyengine_api/api.py", "app = None\n")
    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "--message", "Merge pull request #4116")
    return repository, _git(repository, "rev-parse", "HEAD")


def _commit_release(repository: Path, *, extra_change: bool = False) -> None:
    """Commit what the versioning job commits, and optionally one change more."""
    _write(repository, "pyproject.toml", _bumped(PYPROJECT))
    _write(repository, "uv.lock", _bumped(LOCK))
    _write(
        repository,
        "CHANGELOG.md",
        "## [5.14.3] - 2026-10-29\n\n### Fixed\n\n- Return 404.\n\n" + CHANGELOG,
    )
    (repository / FRAGMENT).unlink()
    if extra_change:
        _write(repository, "policyengine_api/api.py", "app = object()\n")
    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "--message", "Update PolicyEngine API")


def _fake_gh(tmp_path: Path, merge_commit: str, jobs: list[dict]) -> Path:
    """Put a gh first on PATH that answers the two Actions API requests."""
    responses = tmp_path / "responses"
    responses.mkdir()
    runs_path = (
        f"repos/{REPOSITORY}/actions/workflows/push.yml/runs"
        f"?head_sha={merge_commit}&event=push&per_page=100"
    )
    (responses / "runs.json").write_text(
        json.dumps({"workflow_runs": [{"id": 101, "html_url": MERGE_RUN_URL}]})
    )
    (responses / "jobs.json").write_text(json.dumps({"jobs": jobs}))
    jobs_path = f"repos/{REPOSITORY}/actions/runs/101/jobs?per_page=100"
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    gh = bin_directory / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        f'if [[ "$*" == "api {runs_path}" ]]; then cat "{responses}/runs.json"\n'
        f'elif [[ "$*" == "api {jobs_path}" ]]; then cat "{responses}/jobs.json"\n'
        'else echo "unexpected gh call: $*" >&2; exit 1; fi\n'
    )
    gh.chmod(0o755)
    return bin_directory


def _run_check(repository: Path, bin_directory: Path, tmp_path: Path):
    output_path = tmp_path / "github_output"
    output_path.touch()
    result = subprocess.run(
        ["bash", str(CHECK_SCRIPT)],
        cwd=repository,
        env={
            **_git_environment(),
            "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
            "GH_TOKEN": "fake-token",
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_OUTPUT": str(output_path),
            "PYTHON": sys.executable,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    outputs = dict(
        line.split("=", 1) for line in output_path.read_text().splitlines() if line
    )
    return result, outputs


def test_a_release_commit_whose_merge_run_passed_skips_the_checks(tmp_path: Path):
    repository, merge_commit = _merge_commit_repository(tmp_path)
    _commit_release(repository)
    bin_directory = _fake_gh(tmp_path, merge_commit, _passing_jobs())

    result, outputs = _run_check(repository, bin_directory, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs == {
        "merge_run_checks_passed": "true",
        "merge_run_url": MERGE_RUN_URL,
    }


def test_a_release_commit_with_another_change_runs_the_checks(tmp_path: Path):
    repository, merge_commit = _merge_commit_repository(tmp_path)
    _commit_release(repository, extra_change=True)
    bin_directory = _fake_gh(tmp_path, merge_commit, _passing_jobs())

    result, outputs = _run_check(repository, bin_directory, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs["merge_run_checks_passed"] == "false"
    assert "::notice::policyengine_api/api.py is not a release file" in result.stdout


def test_a_release_commit_whose_merge_run_failed_a_check_runs_them(tmp_path: Path):
    repository, merge_commit = _merge_commit_repository(tmp_path)
    _commit_release(repository)
    jobs = _passing_jobs()
    jobs[0]["conclusion"] = "failure"
    bin_directory = _fake_gh(tmp_path, merge_commit, jobs)

    result, outputs = _run_check(repository, bin_directory, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs["merge_run_checks_passed"] == "false"
    assert "Lint ended completed, failure" in result.stdout


def test_the_checks_run_when_the_actions_api_cannot_be_read(tmp_path: Path):
    repository, _merge_commit = _merge_commit_repository(tmp_path)
    _commit_release(repository)
    bin_directory = _fake_gh(tmp_path, "another-commit", _passing_jobs())

    result, outputs = _run_check(repository, bin_directory, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs == {"merge_run_checks_passed": "false", "merge_run_url": ""}
    assert "Could not list the Push runs of the parent" in result.stdout


def test_the_checks_run_when_the_release_commit_is_a_merge(tmp_path: Path):
    repository, merge_commit = _merge_commit_repository(tmp_path)
    _git(repository, "checkout", "--quiet", "-b", "other")
    _write(repository, "README.md", "Other.\n")
    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "--message", "Other")
    _git(repository, "checkout", "--quiet", "master")
    _git(repository, "merge", "--quiet", "--no-ff", "--message", "Merge", "other")
    bin_directory = _fake_gh(tmp_path, merge_commit, _passing_jobs())

    result, outputs = _run_check(repository, bin_directory, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs["merge_run_checks_passed"] == "false"
    assert "exactly one parent" in result.stdout
