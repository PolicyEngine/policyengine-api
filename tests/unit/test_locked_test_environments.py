"""CI test jobs install from uv.lock and run their tests through it.

The Cloud Run image installs with ``uv sync --frozen`` from uv.lock
(gcp/cloud_run/Dockerfile). A test job that installs with pip instead resolves
the newest releases on PyPI, so its tests run against versions production does
not run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.rules.workflows import parse_jobs

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_DIRECTORY = REPO / ".github" / "workflows"
LOCKED_SYNC = "uv sync --frozen --extra dev"
LOCKED_RUN = "uv run --frozen --extra dev"
# The Cloud Run image runs on python:3.12-slim; .python-version selects 3.14.
PRODUCTION_PYTHON_SETTING = 'UV_PYTHON: "3.12"'
SCRIPT_REFERENCE = re.compile(r"\.github/[\w./-]+\.sh")
MAKE_TARGET_REFERENCE = re.compile(r"\bmake ([\w-]+)")
TEST_COMMAND = re.compile(r"\bpytest\b|\bcoverage (run|xml)\b")
MAKE_TARGET_HEADER = re.compile(r"^([\w-]+)\s*:(?!=)")
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
# Operational jobs that run application code against real databases with the
# interpreter setup-python provides. They keep an explicit unlocked install
# until moving them to uv.lock is verified on its own.
UNLOCKED_OPERATIONAL_JOBS = {
    ("migrate-v1-cloud-sql.yml", "migrate"),
    ("process-v1-household-mirror-event.yml", "process-event"),
}
EXPLICIT_UNLOCKED_INSTALL = 'pip install -e ".[dev]"'


def _makefile_recipes() -> dict[str, list[str]]:
    recipes: dict[str, list[str]] = {}
    current_target = None
    for makefile_line in (REPO / "Makefile").read_text(encoding="utf-8").splitlines():
        header = MAKE_TARGET_HEADER.match(makefile_line)
        if header is not None and header.group(1) != ".PHONY":
            current_target = header.group(1)
            recipes[current_target] = []
        elif makefile_line.startswith("\t") and current_target is not None:
            recipes[current_target].append(makefile_line.strip())
        elif makefile_line.strip():
            current_target = None
    return recipes


def _executed_lines(command_text: str, visited: set[str] | None = None) -> list[str]:
    """Return the command's lines plus those of the scripts and Make targets it runs."""
    visited = set() if visited is None else visited
    recipes = _makefile_recipes()
    executed = []
    for command_line in command_text.splitlines():
        executed.append(command_line)
        for script_path in SCRIPT_REFERENCE.findall(command_line):
            if script_path in visited or not (REPO / script_path).is_file():
                continue
            visited.add(script_path)
            script_text = (REPO / script_path).read_text(encoding="utf-8")
            executed += _executed_lines(script_text, visited)
        for target in MAKE_TARGET_REFERENCE.findall(command_line):
            if f"make {target}" in visited or target not in recipes:
                continue
            visited.add(f"make {target}")
            executed += _executed_lines("\n".join(recipes[target]), visited)
    return executed


def _job_text(workflow_text: str, job_id: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_id)}:\n(?P<body>.*?)(?=^  [\w-]+:\n|\Z)",
        workflow_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing workflow job {job_id}"
    return match.group("body")


def _workflow_jobs() -> list[tuple[str, str, str, list[str]]]:
    """Return (workflow, job, job text, executed lines) for every workflow job."""
    jobs = []
    for workflow_path in sorted(WORKFLOW_DIRECTORY.glob("*.y*ml")):
        workflow_text = workflow_path.read_text(encoding="utf-8")
        parsed_jobs, problems = parse_jobs(workflow_text)
        assert problems == [], f"{workflow_path.name}: {problems}"
        for job_id, job in parsed_jobs.items():
            executed = []
            for run_block in job.run_blocks:
                executed += _executed_lines(run_block.text)
            jobs.append(
                (
                    workflow_path.name,
                    job_id,
                    _job_text(workflow_text, job_id),
                    executed,
                )
            )
    return jobs


def _test_jobs() -> list[tuple[str, str, str, list[str]]]:
    return [
        job
        for job in _workflow_jobs()
        if any(TEST_COMMAND.search(executed_line) for executed_line in job[3])
    ]


def _test_job_id(job: tuple[str, str, str, list[str]]) -> str:
    return f"{job[0]}:{job[1]}"


def test_detects_every_known_test_job():
    found = {(workflow, job_id) for workflow, job_id, _, _ in _test_jobs()}

    assert found >= EXPECTED_TEST_JOBS


def test_make_install_syncs_the_locked_development_environment():
    assert _makefile_recipes()["install"] == [LOCKED_SYNC]


@pytest.mark.parametrize("target", ["test", "test-env-vars", "debug-test"])
def test_make_test_targets_run_through_the_locked_environment(target):
    recipe = _makefile_recipes()[target]
    test_commands = [
        recipe_line for recipe_line in recipe if TEST_COMMAND.search(recipe_line)
    ]

    assert test_commands
    assert all(LOCKED_RUN in recipe_line for recipe_line in test_commands), recipe


def test_makefile_runs_the_production_python_version():
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    assert re.search(r"^export UV_PYTHON \?= 3\.12$", makefile, flags=re.MULTILINE)


@pytest.mark.parametrize("job", _test_jobs(), ids=_test_job_id)
def test_test_job_installs_nothing_outside_the_lock(job):
    _, _, _, executed = job
    unlocked_installs = [
        executed_line for executed_line in executed if "pip install" in executed_line
    ]

    assert unlocked_installs == []


@pytest.mark.parametrize("job", _test_jobs(), ids=_test_job_id)
def test_test_job_runs_every_test_command_through_the_lock(job):
    _, _, _, executed = job
    unlocked_test_commands = [
        executed_line
        for executed_line in executed
        if TEST_COMMAND.search(executed_line) and "uv run --frozen" not in executed_line
    ]

    assert unlocked_test_commands == []


@pytest.mark.parametrize("job", _test_jobs(), ids=_test_job_id)
def test_test_job_selects_the_production_python_version(job):
    _, _, job_text, _ = job

    assert PRODUCTION_PYTHON_SETTING in job_text


@pytest.mark.parametrize(
    ("workflow", "job_id"), sorted(UNLOCKED_OPERATIONAL_JOBS), ids=str
)
def test_operational_job_keeps_an_explicit_install_for_its_python(workflow, job_id):
    jobs = {(name, job): executed for name, job, _, executed in _workflow_jobs()}
    executed = jobs[(workflow, job_id)]

    # make install now syncs .venv, which the job's bare python never reads.
    assert EXPLICIT_UNLOCKED_INSTALL in executed
    assert "make install" not in executed
