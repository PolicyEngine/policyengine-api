"""Tests for the wiring of .github/workflows/relock-dependencies.yml.

The scripts it runs are tested in test_relock_dependencies_script.py and
test_relock_pull_request_script.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/relock-dependencies.yml"
PUSH_WORKFLOW = REPO / ".github/workflows/push.yml"
APP_TOKEN = "${{ steps.app-token.outputs.token }}"
SUMMARY_FILE = "${{ runner.temp }}/relock-summary.md"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def relock_job(workflow: dict) -> dict:
    return workflow["jobs"]["relock"]


def _step(job: dict, *, uses: str | None = None, run: str | None = None) -> dict:
    """Return the one step that uses the ``uses`` action or runs ``run``."""
    if uses is not None:
        matches = [
            step for step in job["steps"] if step.get("uses", "").startswith(uses)
        ]
    else:
        matches = [step for step in job["steps"] if step.get("run") == run]
    (step,) = matches
    return step


def test_runs_daily_and_on_manual_dispatch(workflow: dict) -> None:
    # PyYAML reads the bare key "on" as the boolean True.
    triggers = workflow[True]

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    (schedule,) = triggers["schedule"]
    minute, hour, day, month, weekday = schedule["cron"].split()
    assert (day, month, weekday) == ("*", "*", "*")
    assert minute.isdigit()
    assert hour.isdigit()


def test_runs_only_in_the_canonical_repository_with_a_read_only_token(
    workflow: dict, relock_job: dict
) -> None:
    assert relock_job["if"] == "github.repository == 'PolicyEngine/policyengine-api'"
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_checks_out_and_opens_the_pull_request_with_the_app_token(
    relock_job: dict,
) -> None:
    token_step = _step(relock_job, uses="actions/create-github-app-token@")
    assert token_step["id"] == "app-token"
    assert token_step["with"] == {
        "app-id": "${{ secrets.APP_ID }}",
        "private-key": "${{ secrets.APP_PRIVATE_KEY }}",
    }
    checkout = _step(relock_job, uses="actions/checkout@")
    assert checkout["with"]["token"] == APP_TOKEN

    pull_request_step = _step(
        relock_job, run="bash .github/scripts/open_relock_pull_request.sh"
    )
    assert pull_request_step["env"]["GH_TOKEN"] == APP_TOKEN


def test_relocks_with_python_312_and_the_uv_version_that_locks_releases(
    relock_job: dict,
) -> None:
    setup_python = _step(relock_job, uses="actions/setup-python@")
    assert setup_python["with"]["python-version"] == "3.12"
    assert relock_job["env"]["RELOCK_PYTHON"] == "3.12"

    push_jobs = yaml.safe_load(PUSH_WORKFLOW.read_text())["jobs"]
    release_uv = _step(push_jobs["versioning"], uses="astral-sh/setup-uv@")
    relock_uv = _step(relock_job, uses="astral-sh/setup-uv@")
    assert relock_uv["uses"] == release_uv["uses"]
    assert relock_uv["with"]["version"] == release_uv["with"]["version"]


def test_opens_a_pull_request_only_when_the_lock_changed(relock_job: dict) -> None:
    relock_step = _step(relock_job, run="bash .github/scripts/relock_dependencies.sh")
    pull_request_step = _step(
        relock_job, run="bash .github/scripts/open_relock_pull_request.sh"
    )

    assert relock_step["id"] == "relock"
    assert pull_request_step["if"] == "steps.relock.outputs.changed == 'true'"
    assert relock_step["env"]["RELOCK_SUMMARY_FILE"] == SUMMARY_FILE
    assert pull_request_step["env"]["RELOCK_SUMMARY_FILE"] == SUMMARY_FILE
    steps = relock_job["steps"]
    assert steps.index(relock_step) < steps.index(pull_request_step)


def test_proposes_master_relocks_from_the_fixed_branch(relock_job: dict) -> None:
    assert relock_job["env"]["BASE_BRANCH"] == "${{ github.ref_name }}"
    assert relock_job["env"]["RELOCK_BRANCH"] == (
        "${{ github.ref_name == 'master' && 'auto/relock-dependencies' "
        "|| format('auto/relock-dependencies-{0}', github.ref_name) }}"
    )
