"""The cross-database integration check, .github/workflows/v2-integration-check.yml.

The check has one job, catalog-runtime-integration, which never loads the
complete installed PolicyEngine.py catalog. It publishes a few parameter
folders of the installed models instead
(tests/integration/test_v2_catalog_installed_folders.py), on every run.
"""

from __future__ import annotations

import yaml

from tests.unit.cloud_run_deploy_support import REPO, job_step

WORKFLOW_PATH = REPO / ".github/workflows/v2-integration-check.yml"
RUNTIME_JOB = "catalog-runtime-integration"
INSTALLED_FOLDERS_STEP = (
    "Publish selected parameter folders of the installed PolicyEngine.py models"
)
INSTALLED_FOLDERS_TEST = "tests/integration/test_v2_catalog_installed_folders.py"
REMOVED_FULL_CATALOG_FILES = (
    "tests/integration/test_v2_catalog_installed.py",
    "tests/integration/test_v2_catalog_publication_qualification.py",
    "tests/fixtures/installed_catalog.py",
)


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _workflow() -> dict:
    return yaml.safe_load(_workflow_text())


def _triggers() -> dict:
    workflow = _workflow()
    # PyYAML reads the bare key "on" as True.
    return workflow.get("on", workflow.get(True))


def _runtime_job() -> dict:
    return _workflow()["jobs"][RUNTIME_JOB]


def _step_commands(job: dict) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def test_the_workflow_runs_when_called_or_dispatched() -> None:
    triggers = _triggers()

    assert set(triggers) == {"workflow_call", "workflow_dispatch"}
    # Its callers upload its coverage report, so it takes no secret.
    assert triggers["workflow_call"] is None


def test_the_check_has_one_job_that_always_runs_every_step() -> None:
    jobs = _workflow()["jobs"]

    assert set(jobs) == {RUNTIME_JOB}
    assert "if" not in jobs[RUNTIME_JOB]
    for step in jobs[RUNTIME_JOB]["steps"]:
        assert "if" not in step, step["name"]


def test_no_step_loads_the_complete_installed_catalog() -> None:
    workflow_text = _workflow_text()

    for removed_path in REMOVED_FULL_CATALOG_FILES:
        assert removed_path not in workflow_text
        assert not (REPO / removed_path).exists(), removed_path
    assert "RUN_V2_CATALOG_COMPATIBILITY" not in workflow_text
    assert "RUN_V2_CATALOG_PUBLICATION_QUALIFICATION" not in workflow_text


def test_the_job_publishes_selected_folders_of_the_installed_models() -> None:
    job = _runtime_job()
    step = job_step(job, INSTALLED_FOLDERS_STEP)
    commands = _step_commands(job)

    assert step["run"] == (
        "uv run --frozen --extra dev coverage run -a --branch -m pytest -q "
        f"--durations=10 {INSTALLED_FOLDERS_TEST}"
    )
    assert "env" not in step
    # After the schema upgrade and the role checks, like the other test steps.
    assert commands.index(
        "uv run --frozen --extra dev python scripts/reconcile_v2_privileges.py verify"
    ) < commands.index(step["run"])
    assert (REPO / INSTALLED_FOLDERS_TEST).exists()
