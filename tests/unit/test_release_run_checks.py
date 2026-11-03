"""push.yml's release runs: the checks they may skip, and that no deploy is skipped.

A release run skips lint, the quality guards, the Alembic v1 and v2 checks and
the cross-database integration tests when check-release-commit finds that the
release commit changes only release files and its merge run passed them
(.github/release_commit.py; tests/unit/test_release_commit.py).

GitHub skips a job whose needs include a skipped or failed job, directly or
through the jobs between them, unless the job's ``if:`` calls a status function
such as ``!cancelled()``. Every release job therefore calls ``!cancelled()`` and
checks the result of each job it needs itself, and so does each job of the
reusable workflows they call. Without that, skipping the checks would skip
every deploy job after them, and the run would still finish green.
"""

from __future__ import annotations

import pytest
import yaml

from tests.unit.cloud_run_deploy_support import (
    REPO,
    job_needs,
    job_step,
    push_workflow_jobs,
)

RELEASE_COMMIT_CHECK_JOB = "check-release-commit"
PUBLISH_TAG_JOB = "publish-git-tag"
REPOSITORY_CONDITION = "github.repository == 'PolicyEngine/policyengine-api'"
RELEASE_COMMIT = "github.event.head_commit.message == 'Update PolicyEngine API'"
RELEASE_CONDITION = f"({REPOSITORY_CONDITION})\n&& ({RELEASE_COMMIT})\n"
SKIP_CONDITION = "needs.check-release-commit.outputs.merge_run_checks_passed != 'true'"
# release_commit.MERGE_RUN_CHECKS and RELEASE_RUN_REQUIRED_CHECKS; that
# module's tests check they match.
CHECK_JOBS = (
    "lint",
    "quality-guards",
    "alembic-v1-check",
    "alembic-v2-check",
    "v2-integration-check",
)
REQUIRED_CHECKS = (
    "lint",
    "alembic-v1-check",
    "alembic-v2-check",
    "v2-integration-check",
)


def _is_release_job(job: dict) -> bool:
    return f"&& ({RELEASE_COMMIT})" in job.get("if", "")


def _release_jobs() -> dict[str, dict]:
    return {
        job_id: job
        for job_id, job in push_workflow_jobs().items()
        if _is_release_job(job)
    }


def test_check_release_commit_runs_on_every_push_and_decides_on_release_commits():
    job = push_workflow_jobs()[RELEASE_COMMIT_CHECK_JOB]
    decision = job_step(job, "Decide whether this run may skip the merge run's checks")

    # It runs on merge runs too, so the checks that need it never need a
    # skipped job there; its steps do nothing on a merge commit.
    assert job["if"] == REPOSITORY_CONDITION
    assert job_needs(job) == []
    for step in job["steps"]:
        assert step["if"] == RELEASE_COMMIT
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    assert job_step(job, "Checkout the release commit and its parent")["with"] == {
        "fetch-depth": 2
    }
    assert decision["id"] == "release_commit"
    assert decision["run"] == "bash .github/scripts/check_release_commit.sh"
    assert decision["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert job["outputs"] == {
        "merge_run_checks_passed": (
            "${{ steps.release_commit.outputs.merge_run_checks_passed }}"
        ),
        "merge_run_url": "${{ steps.release_commit.outputs.merge_run_url }}",
    }


@pytest.mark.parametrize("check_job", CHECK_JOBS)
def test_each_merge_run_check_runs_unless_the_release_commit_check_skips_it(
    check_job,
):
    job = push_workflow_jobs()[check_job]

    assert job_needs(job) == [RELEASE_COMMIT_CHECK_JOB]
    # !cancelled(): when the release commit check fails, the checks run.
    assert job["if"] == (
        f"!cancelled()\n&& ({REPOSITORY_CONDITION})\n&& ({SKIP_CONDITION})\n"
    )


def test_publish_git_tag_requires_the_merge_runs_checks_or_its_own():
    job = push_workflow_jobs()[PUBLISH_TAG_JOB]
    step_names = [step["name"] for step in job["steps"]]
    requirement = job_step(job, "Require the merge run's checks or this run's")

    assert set(job_needs(job)) == {
        "ensure-staging-model-version-aligns-with-sim-api",
        RELEASE_COMMIT_CHECK_JOB,
        *REQUIRED_CHECKS,
    }
    assert job["if"] == (
        f"!cancelled()\n&& ({REPOSITORY_CONDITION})\n&& ({RELEASE_COMMIT})\n"
        "&& needs.ensure-staging-model-version-aligns-with-sim-api.result == "
        "'success'\n"
    )
    # Before the tag, and so before anything that deploys.
    assert step_names.index(requirement["name"]) < step_names.index("Publish Git Tag")
    assert requirement["run"] == "python .github/release_commit.py require-checks"
    assert requirement["env"] == {"JOB_RESULTS": "${{ toJSON(needs) }}"}


def test_every_release_job_checks_each_job_it_needs():
    # publish-git-tag's release_commit.py require-checks step reads the
    # results of the checks and of check-release-commit.
    read_by_require_checks = {RELEASE_COMMIT_CHECK_JOB, *CHECK_JOBS}

    for job_id, job in _release_jobs().items():
        needs = job_needs(job)
        if not needs:
            assert job["if"] == RELEASE_CONDITION, job_id
            continue
        assert job["if"].startswith(f"!cancelled()\n&& ({REPOSITORY_CONDITION})\n"), (
            job_id
        )
        for needed_job in needs:
            if job_id == PUBLISH_TAG_JOB and needed_job in read_by_require_checks:
                continue
            assert f"needs.{needed_job}.result == 'success'" in job["if"], (
                f"{job_id} must check that {needed_job} passed"
            )


def test_only_publish_git_tag_waits_for_the_checks_a_release_run_may_skip():
    skippable_jobs = {RELEASE_COMMIT_CHECK_JOB, *CHECK_JOBS}

    for job_id, job in _release_jobs().items():
        if job_id != PUBLISH_TAG_JOB:
            assert not skippable_jobs & set(job_needs(job)), job_id


def test_reusable_workflows_called_by_release_jobs_run_their_jobs_unless_cancelled():
    called_workflows = sorted(
        {
            job["uses"].removeprefix("./")
            for job in _release_jobs().values()
            if "uses" in job and job_needs(job)
        }
    )

    assert called_workflows == [
        ".github/workflows/migrate-v1-cloud-sql.yml",
        ".github/workflows/seed-v2-database.yml",
    ]
    for called_workflow in called_workflows:
        workflow = yaml.safe_load((REPO / called_workflow).read_text(encoding="utf-8"))
        for job_id, job in workflow["jobs"].items():
            assert job.get("if") == "${{ !cancelled() }}", (called_workflow, job_id)
