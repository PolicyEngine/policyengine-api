"""The full-catalog job in .github/workflows/v2-integration-check.yml.

Two integration tests load the complete installed PolicyEngine.py catalog. They
run in their own job, in one pytest process that extracts the catalog once,
and only when the change can affect them: the job's first step decides
(.github/scripts/decide_full_catalog_tests.sh) and every later step is
conditional on its output. The job itself always runs and passes, because
"CI complete" fails on a skipped job and a release run may skip the
cross-database integration tests only when every job of its merge run's check
succeeded (.github/release_commit.py).
"""

from __future__ import annotations

import yaml

from tests.unit.cloud_run_deploy_support import REPO, job_step

WORKFLOW_PATH = REPO / ".github/workflows/v2-integration-check.yml"
FULL_CATALOG_JOB = "full-catalog-integration"
RUNTIME_JOB = "catalog-runtime-integration"
DECISION_STEP = "Decide whether this change can affect the full-catalog tests"
DECISION_ID = "full_catalog"
RUN_CONDITION = "steps.full_catalog.outputs.run_full_catalog_tests == 'true'"
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


def test_the_workflow_runs_on_call_on_dispatch_and_every_night() -> None:
    triggers = _triggers()

    assert set(triggers) == {"workflow_call", "workflow_dispatch", "schedule"}
    assert triggers["workflow_call"]["secrets"] == {
        "CODECOV_TOKEN": {"required": False}
    }
    assert len(triggers["schedule"]) == 1
    minute, hour, day_of_month, month, day_of_week = triggers["schedule"][0][
        "cron"
    ].split()
    assert minute.isdigit()
    assert hour.isdigit()
    assert (day_of_month, month, day_of_week) == ("*", "*", "*")


def test_the_full_catalog_job_always_runs() -> None:
    job = _full_catalog_job()

    # A job-level condition could skip the job, which fails "CI complete" and
    # makes a release run repeat the check.
    assert "if" not in job
    assert "needs" not in job
    assert job["name"] == "Full installed PolicyEngine.py catalog"


def test_the_first_steps_check_out_history_and_decide() -> None:
    job = _full_catalog_job()
    checkout, decision = job["steps"][:2]

    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"] == {"fetch-depth": 0}
    assert "if" not in checkout
    assert decision["name"] == DECISION_STEP
    assert decision["id"] == DECISION_ID
    assert decision["run"] == "bash .github/scripts/decide_full_catalog_tests.sh"
    assert decision["env"] == {
        "EVENT_NAME": "${{ github.event_name }}",
        "BASE_SHA": (
            "${{ github.event.pull_request.base.sha || github.event.before }}"
        ),
    }
    assert "if" not in decision


def test_every_step_after_the_decision_runs_only_when_it_says_so() -> None:
    later_steps = _full_catalog_job()["steps"][2:]

    assert later_steps
    for step in later_steps:
        assert step.get("if") == RUN_CONDITION, step["name"]


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
