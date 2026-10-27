"""CI test jobs install from uv.lock, on the Python version production runs.

The Cloud Run image installs with ``uv sync --frozen`` from uv.lock
(gcp/cloud_run/Dockerfile) on Python 3.12. The locked-installs quality guard
(scripts/rules/locked_installs.py, docs/engineering/skills/dependencies.md)
reports every install and test command in the repository that bypasses
uv.lock; these tests check what it does not: the Make targets CI calls, the
Python version each test job selects, and how the operational database jobs
install and run their scripts.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest

from scripts.rules.locked_installs import executed_lines, makefile_recipes
from scripts.rules.workflows import parse_jobs

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_DIRECTORY = REPO / ".github" / "workflows"
LOCKED_SYNC = "uv sync --frozen --extra dev"
LOCKED_RUN = "uv run --frozen --extra dev"
# The Cloud Run image runs on python:3.12-slim; .python-version selects 3.14.
PRODUCTION_PYTHON_SETTING = 'UV_PYTHON: "3.12"'
TEST_COMMAND = re.compile(r"\bpytest\b|\bcoverage (run|xml)\b")
# The test jobs this module must find; a smaller set means the detection broke.
EXPECTED_TEST_JOBS = {
    ("alembic-v1-check.yml", "mysql-lifecycle"),
    ("alembic-v2-check.yml", "postgres-lifecycle"),
    ("pr.yml", "test"),
    ("pr.yml", "test_env_vars"),
    ("push.yml", "deploy-cloud-run-candidate"),
    ("push.yml", "deploy-cloud-run-staging"),
    ("push.yml", "parallel-live-simulation-tests-staging-cloud-run"),
    ("v2-integration-check.yml", "catalog-runtime-integration"),
}
# Operational jobs that run application code against the staging and
# production databases. They install the runtime dependencies from uv.lock, as
# the Cloud Run image does, and run every Python script through uv run --frozen.
OPERATIONAL_DATABASE_JOBS = {
    ("migrate-v1-cloud-sql.yml", "migrate"),
}
# An operational job that still installs unlocked, under a registered
# exception, until moving it to uv.lock is verified on its own.
UNLOCKED_OPERATIONAL_JOBS = {
    ("process-v1-household-mirror-event.yml", "process-event"),
}
EXPLICIT_UNLOCKED_INSTALL = 'pip install -e ".[dev]"'
RUNTIME_LOCKED_SYNC = "uv sync --frozen"
LOCKED_SCRIPT_RUN = "uv run --frozen python scripts/"
PYTHON_SCRIPT_COMMAND = re.compile(r"\bpython\s+scripts/")


class WorkflowJob(NamedTuple):
    """One workflow job and every command line it runs."""

    workflow: str
    job_id: str
    job_text: str
    executed_lines: list[str]


def _job_text(workflow_text: str, job_id: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_id)}:\n(?P<body>.*?)(?=^  [\w-]+:\n|\Z)",
        workflow_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing workflow job {job_id}"
    return match.group("body")


def _workflow_jobs() -> list[WorkflowJob]:
    """Return every workflow job with the command lines it runs."""
    jobs = []
    for workflow_path in sorted(WORKFLOW_DIRECTORY.glob("*.y*ml")):
        workflow_text = workflow_path.read_text(encoding="utf-8")
        parsed_jobs, problems = parse_jobs(workflow_text)
        assert problems == [], f"{workflow_path.name}: {problems}"
        for job_id, job in parsed_jobs.items():
            executed = []
            for run_block in job.run_blocks:
                executed += executed_lines(REPO, run_block.text)
            jobs.append(
                WorkflowJob(
                    workflow_path.name,
                    job_id,
                    _job_text(workflow_text, job_id),
                    executed,
                )
            )
    return jobs


def _test_jobs() -> list[WorkflowJob]:
    return [
        job
        for job in _workflow_jobs()
        if any(
            TEST_COMMAND.search(executed_line) for executed_line in job.executed_lines
        )
    ]


def _test_job_id(job: WorkflowJob) -> str:
    return f"{job.workflow}:{job.job_id}"


def test_detects_every_known_test_job():
    found = {(job.workflow, job.job_id) for job in _test_jobs()}

    assert found >= EXPECTED_TEST_JOBS


def test_make_install_syncs_the_locked_development_environment():
    assert makefile_recipes(REPO)["install"] == [LOCKED_SYNC]


@pytest.mark.parametrize("target", ["test", "test-env-vars", "debug-test"])
def test_make_test_targets_run_through_the_locked_environment(target):
    recipe = makefile_recipes(REPO)[target]
    test_commands = [
        recipe_line for recipe_line in recipe if TEST_COMMAND.search(recipe_line)
    ]

    assert test_commands
    assert all(LOCKED_RUN in recipe_line for recipe_line in test_commands), recipe


def test_makefile_runs_the_production_python_version():
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    assert re.search(r"^export UV_PYTHON \?= 3\.12$", makefile, flags=re.MULTILINE)


@pytest.mark.parametrize("job", _test_jobs(), ids=_test_job_id)
def test_test_job_selects_the_production_python_version(job):
    assert PRODUCTION_PYTHON_SETTING in job.job_text


def _operational_job(workflow: str, job_id: str) -> WorkflowJob:
    jobs = {(job.workflow, job.job_id): job for job in _workflow_jobs()}
    return jobs[(workflow, job_id)]


@pytest.mark.parametrize(
    ("workflow", "job_id"), sorted(UNLOCKED_OPERATIONAL_JOBS), ids=str
)
def test_operational_job_keeps_an_explicit_install_for_its_python(workflow, job_id):
    executed = _operational_job(workflow, job_id).executed_lines

    # make install now syncs .venv, which the job's bare python never reads.
    assert EXPLICIT_UNLOCKED_INSTALL in executed
    assert "make install" not in executed


@pytest.mark.parametrize(
    ("workflow", "job_id"), sorted(OPERATIONAL_DATABASE_JOBS), ids=str
)
def test_operational_job_installs_the_locked_runtime_dependencies(workflow, job_id):
    executed = [
        executed_line.strip()
        for executed_line in _operational_job(workflow, job_id).executed_lines
    ]

    assert RUNTIME_LOCKED_SYNC in executed
    assert not [
        executed_line for executed_line in executed if "pip install" in executed_line
    ]


@pytest.mark.parametrize(
    ("workflow", "job_id"), sorted(OPERATIONAL_DATABASE_JOBS), ids=str
)
def test_operational_job_runs_every_python_script_through_the_lock(workflow, job_id):
    script_commands = [
        executed_line
        for executed_line in _operational_job(workflow, job_id).executed_lines
        if PYTHON_SCRIPT_COMMAND.search(executed_line)
    ]

    assert script_commands, f"{workflow} {job_id} runs no Python script"
    assert all(
        LOCKED_SCRIPT_RUN in script_command for script_command in script_commands
    ), script_commands


@pytest.mark.parametrize(
    ("workflow", "job_id"), sorted(OPERATIONAL_DATABASE_JOBS), ids=str
)
def test_operational_job_selects_the_production_python_version(workflow, job_id):
    assert PRODUCTION_PYTHON_SETTING in _operational_job(workflow, job_id).job_text


def _setup_uv_version(workflow: str, job_id: str) -> str:
    workflow_text = (WORKFLOW_DIRECTORY / workflow).read_text(encoding="utf-8")
    versions = re.findall(
        r'uses: astral-sh/setup-uv@\S+\n\s+with:\n\s+version: "([^"]+)"',
        _job_text(workflow_text, job_id),
    )
    assert len(versions) == 1, f"{workflow} {job_id} must pin one setup-uv version"
    return versions[0]


def test_lock_check_uses_the_uv_version_that_locks_releases():
    # quality-guards runs uv lock --check; a different uv can read or write
    # another lock revision than the versioning job's uv lock does.
    assert _setup_uv_version("pr.yml", "quality-guards") == _setup_uv_version(
        "push.yml", "versioning"
    )


@pytest.mark.parametrize(
    ("workflow", "job_id"), sorted(OPERATIONAL_DATABASE_JOBS), ids=str
)
def test_operational_job_uses_the_uv_version_that_locks_releases(workflow, job_id):
    # A different uv can read another lock revision than the one the
    # versioning job's uv lock writes.
    assert _setup_uv_version(workflow, job_id) == _setup_uv_version(
        "push.yml", "versioning"
    )
