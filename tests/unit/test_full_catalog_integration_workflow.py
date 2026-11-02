"""The full-catalog job in .github/workflows/v2-integration-check.yml.

Two integration tests load the complete installed PolicyEngine.py catalog. They
run on every run of the workflow, in their own job beside
catalog-runtime-integration, in one pytest process that extracts the catalog
once. No step of the job is conditional, so the cross-database check takes as
long as the slower of its two jobs.
"""

from __future__ import annotations

import yaml

from tests.unit.cloud_run_deploy_support import REPO, job_step

WORKFLOW_PATH = REPO / ".github/workflows/v2-integration-check.yml"
FULL_CATALOG_JOB = "full-catalog-integration"
RUNTIME_JOB = "catalog-runtime-integration"
FULL_CATALOG_TESTS = (
    "tests/integration/test_v2_catalog_installed.py",
    "tests/integration/test_v2_catalog_publication_qualification.py",
)
FULL_CATALOG_TEST_STEP = (
    "Verify the installed catalog interface and qualify production-scale publication"
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _triggers() -> dict:
    workflow = _workflow()
    # PyYAML reads the bare key "on" as True.
    return workflow.get("on", workflow.get(True))


def _full_catalog_job() -> dict:
    return _workflow()["jobs"][FULL_CATALOG_JOB]


def _step_commands(job: dict) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def test_the_workflow_runs_when_called_or_dispatched() -> None:
    triggers = _triggers()

    # No schedule: every pull request and push already runs both tests.
    assert set(triggers) == {"workflow_call", "workflow_dispatch"}
    assert triggers["workflow_call"]["secrets"] == {
        "CODECOV_TOKEN": {"required": False}
    }


def test_the_full_catalog_job_always_runs() -> None:
    job = _full_catalog_job()

    assert "if" not in job
    assert "needs" not in job
    assert job["name"] == "Full installed PolicyEngine.py catalog"


def test_no_step_of_the_full_catalog_job_is_conditional() -> None:
    steps = _full_catalog_job()["steps"]

    assert steps
    for step in steps:
        assert "if" not in step, step["name"]
        assert "id" not in step, step["name"]


def test_the_job_checks_out_only_the_commit_it_tests() -> None:
    checkout = _full_catalog_job()["steps"][0]
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert checkout["uses"] == "actions/checkout@v4"
    assert "with" not in checkout
    assert "fetch-depth" not in workflow_text
    assert "decide_full_catalog_tests" not in workflow_text
    assert not (REPO / ".github/scripts/decide_full_catalog_tests.sh").exists()


def test_the_job_reports_the_runner_it_got() -> None:
    commands = _step_commands(_full_catalog_job())

    assert "nproc" in commands
    assert "free -m" in commands
    assert "lscpu" in commands


def test_both_full_catalog_tests_run_in_one_process_with_durations() -> None:
    job = _full_catalog_job()
    test_step = job_step(job, FULL_CATALOG_TEST_STEP)
    pytest_commands = [
        command for command in _step_commands(job) if "pytest" in command
    ]

    assert pytest_commands == [test_step["run"]]
    assert test_step["run"] == (
        "uv run --frozen --extra dev coverage run --branch -m pytest -q "
        "--durations=10 " + " ".join(FULL_CATALOG_TESTS)
    )
    assert test_step["env"] == {
        "RUN_V2_CATALOG_COMPATIBILITY": "1",
        "RUN_V2_CATALOG_PUBLICATION_QUALIFICATION": "1",
    }


def test_the_job_prepares_its_own_disposable_schema_before_the_tests() -> None:
    job = _full_catalog_job()
    commands = _step_commands(job)
    schema_upgrade = commands.index(
        "uv run --frozen --extra dev alembic -c alembic-v2.ini upgrade head"
    )
    tests = commands.index(job_step(job, FULL_CATALOG_TEST_STEP)["run"])

    assert commands.index("uv sync --frozen --extra dev") < schema_upgrade < tests
    assert set(job["services"]) == {"postgres"}
    assert job["services"]["postgres"]["image"] == "postgres:17"
    assert job["env"] == {
        "UV_PYTHON": "3.12",
        "V2_MIGRATION_DATABASE_URL": (
            "postgresql+psycopg://postgres:policyengine_v2_test@127.0.0.1:5432/"
            "policyengine_v2_alembic_test"
        ),
        "V2_ALEMBIC_DISPOSABLE_TEST": "1",
    }


def test_the_job_uploads_its_own_coverage() -> None:
    job = _full_catalog_job()
    upload = job_step(job, "Upload full-catalog coverage to Codecov")

    assert (
        "uv run --frozen --extra dev coverage xml -i -o coverage-v2-full-catalog.xml"
        in _step_commands(job)
    )
    assert upload["uses"] == "codecov/codecov-action@v5"
    assert upload["with"] == {
        "token": "${{ secrets.CODECOV_TOKEN }}",
        "slug": "PolicyEngine/policyengine-api",
        "files": "coverage-v2-full-catalog.xml",
    }


def test_the_runtime_job_no_longer_loads_the_full_catalog() -> None:
    runtime_job = _workflow()["jobs"][RUNTIME_JOB]
    runtime_commands = "\n".join(_step_commands(runtime_job))
    runtime_environment = str([step.get("env", {}) for step in runtime_job["steps"]])

    for test_path in FULL_CATALOG_TESTS:
        assert test_path not in runtime_commands
    assert "RUN_V2_CATALOG_COMPATIBILITY" not in runtime_environment
    assert "RUN_V2_CATALOG_PUBLICATION_QUALIFICATION" not in runtime_environment
