"""Every job that calls a deployed Public API sends its environment's CI credential.

push.yml's deployed-API tests read the Public API's address from
``API_BASE_URL``. Each job that runs them requests one CI server token, from
the Auth0 tenant of the GitHub environment whose deployment it tests, in a step
of its own (``.github/scripts/request_ci_server_token.sh``), and passes it to
the test step as ``CI_SERVER_ACCESS_TOKEN``. The tests send it in
``Authorization: Bearer`` (``tests/integration/deployed_api_credentials.py``).
These tests read every workflow, so a new caller without the credential, or
one that reads another environment's, fails here.
"""

from __future__ import annotations

import pytest
import yaml

from tests.integration.deployed_api_credentials import CI_SERVER_ACCESS_TOKEN_ENV
from tests.unit.cloud_run_deploy_support import (
    PRODUCTION_CLOUD_RUN_SERVICE,
    REPO,
    STAGING_CLOUD_RUN_SERVICE,
    push_workflow_jobs,
)

WORKFLOWS = REPO / ".github/workflows"
TOKEN_STEP_ID = "ci_server_token"
TOKEN_STEP_COMMAND = "bash .github/scripts/request_ci_server_token.sh"
TOKEN_OUTPUT = "${{ steps.ci_server_token.outputs.token }}"
TOKEN_STEP_ENV = {
    "CI_SERVER_AUTH0_DOMAIN": "${{ vars.CI_SERVER_AUTH0_DOMAIN }}",
    "CI_SERVER_AUTH0_CLIENT_ID": "${{ vars.CI_SERVER_AUTH0_CLIENT_ID }}",
    "CI_SERVER_AUTH0_CLIENT_SECRET": "${{ secrets.CI_SERVER_AUTH0_CLIENT_SECRET }}",
    "CI_SERVER_AUTH0_AUDIENCE": "${{ vars.CI_SERVER_AUTH0_AUDIENCE }}",
}
# The tested deployment's own settings, which the script checks the client
# against, from the same GitHub environment.
DEPLOYMENT_AUTH_ENV = {
    "PUBLIC_API_SERVER_AUTH_ISSUER": "${{ vars.PUBLIC_API_SERVER_AUTH_ISSUER }}",
    "PUBLIC_API_AUTH_AUDIENCE": "${{ vars.PUBLIC_API_AUTH_AUDIENCE }}",
    "PUBLIC_API_SERVER_CLIENT_IDS": "${{ vars.PUBLIC_API_SERVER_CLIENT_IDS }}",
}
# A deploy job tests the revision it deployed itself.
OWN_REVISION_URL = "${{ steps.candidate.outputs.url }}"
LIVE_TESTS_CANDIDATE_URL = "${{ needs.deploy-cloud-run-staging.outputs.url }}"
# Each job that calls a deployed Public API: its GitHub environment, and the
# address of the candidate it tests.
DEPLOYED_API_CALLERS = {
    ("push.yml", "deploy-cloud-run-staging"): ("staging", OWN_REVISION_URL),
    ("push.yml", "parallel-live-simulation-tests-staging-cloud-run"): (
        "staging",
        LIVE_TESTS_CANDIDATE_URL,
    ),
    ("push.yml", "deploy-cloud-run-candidate"): ("production", OWN_REVISION_URL),
}
PULL_REQUEST_EVENTS = {"pull_request", "pull_request_target"}
DEPLOY_COMMAND = "bash .github/scripts/deploy_cloud_run_candidate.sh"
# Any way a job could name a deployed Public API to call: an env value at any
# level, a reusable workflow's input, or the baseline tool's argument.
DEPLOYED_API_MARKERS = ("API_BASE_URL", "--base-url")


def _workflows() -> dict[str, dict]:
    """Return every workflow, parsed, keyed by file name."""
    return {
        workflow_path.name: yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        for workflow_path in sorted(
            [*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")]
        )
    }


def _workflow_events(workflow: dict) -> set[str]:
    # YAML 1.1 reads the key ``on`` as True.
    events = workflow.get("on", workflow.get(True))
    if isinstance(events, str):
        return {events}
    return set(events or ())


def _step_env(job: dict, step: dict) -> dict[str, str]:
    """Return what a step's commands see: the job's env, then the step's."""
    return {**(job.get("env") or {}), **(step.get("env") or {})}


def _deployed_api_steps() -> list[tuple[str, str, dict, dict]]:
    """Return (workflow, job id, job, step) for each step that sets API_BASE_URL."""
    return [
        (workflow_name, job_id, job, step)
        for workflow_name, workflow in _workflows().items()
        for job_id, job in workflow["jobs"].items()
        for step in job.get("steps", [])
        if "API_BASE_URL" in (step.get("env") or {})
    ]


def _token_step(job: dict) -> tuple[int, dict]:
    matching_steps = [
        (step_index, step)
        for step_index, step in enumerate(job["steps"])
        if step.get("id") == TOKEN_STEP_ID
    ]
    assert len(matching_steps) == 1, "expected one CI server token step"
    return matching_steps[0]


def test_the_known_jobs_are_the_only_callers_of_a_deployed_public_api() -> None:
    callers = {
        (workflow_name, job_id)
        for workflow_name, workflow in _workflows().items()
        for job_id, job in workflow["jobs"].items()
        if any(marker in yaml.safe_dump(job) for marker in DEPLOYED_API_MARKERS)
    }
    step_callers = {
        (workflow_name, job_id)
        for workflow_name, job_id, _job, _step in _deployed_api_steps()
    }

    assert callers == set(DEPLOYED_API_CALLERS)
    assert step_callers == callers


@pytest.mark.parametrize(("workflow_name", "job_id"), sorted(DEPLOYED_API_CALLERS))
def test_each_caller_requests_its_environments_token_once(
    workflow_name: str, job_id: str
) -> None:
    job = _workflows()[workflow_name]["jobs"][job_id]
    expected_environment, _candidate_url = DEPLOYED_API_CALLERS[(workflow_name, job_id)]

    assert job.get("environment") == expected_environment
    token_step_index, token_step = _token_step(job)
    # The command alone: ::add-mask:: must reach the log, not a redirect. It
    # always runs, and its failure fails the job.
    assert token_step["run"] == TOKEN_STEP_COMMAND
    assert "if" not in token_step
    assert "continue-on-error" not in token_step
    # A missing credential stops a deploy job before a candidate exists.
    deploy_step_indexes = [
        step_index
        for step_index, step in enumerate(job["steps"])
        if step.get("run") == DEPLOY_COMMAND
    ]
    assert all(token_step_index < index for index in deploy_step_indexes)
    # The CI client's settings reach this step only, never the job's env.
    for name, source in TOKEN_STEP_ENV.items():
        assert token_step["env"].get(name) == source, name
    assert set(token_step["env"]) <= {*TOKEN_STEP_ENV, *DEPLOYMENT_AUTH_ENV}
    assert not any(name.startswith("CI_SERVER_") for name in job.get("env") or {})
    token_step_env = _step_env(job, token_step)
    for name, source in DEPLOYMENT_AUTH_ENV.items():
        assert token_step_env.get(name) == source, name
    assert sum(TOKEN_STEP_COMMAND in str(step.get("run")) for step in job["steps"]) == 1


@pytest.mark.parametrize(("workflow_name", "job_id"), sorted(DEPLOYED_API_CALLERS))
def test_each_deployed_api_test_step_sends_the_token(
    workflow_name: str, job_id: str
) -> None:
    job = _workflows()[workflow_name]["jobs"][job_id]
    _expected_environment, candidate_url = DEPLOYED_API_CALLERS[(workflow_name, job_id)]
    token_step_index, _token_step_definition = _token_step(job)
    test_steps = [
        (step_index, step)
        for step_index, step in enumerate(job["steps"])
        if "API_BASE_URL" in (step.get("env") or {})
    ]

    assert len(test_steps) == 1
    ((test_step_index, test_step),) = test_steps
    assert test_step["env"]["API_BASE_URL"] == candidate_url
    assert test_step["env"][CI_SERVER_ACCESS_TOKEN_ENV] == TOKEN_OUTPUT
    assert token_step_index < test_step_index
    # No other step, and no job output, carries the token.
    token_readers = [
        step.get("name")
        for step in job["steps"]
        if "steps.ci_server_token" in str(step)
    ]
    assert token_readers == [test_step["name"]]
    assert "ci_server_token" not in str(job.get("outputs") or {})
    assert CI_SERVER_ACCESS_TOKEN_ENV not in (job.get("env") or {})


def test_each_environment_tests_only_its_own_cloud_run_service() -> None:
    jobs = push_workflow_jobs()

    staging_deploy = jobs["deploy-cloud-run-staging"]
    production_deploy = jobs["deploy-cloud-run-candidate"]
    live_tests = jobs["parallel-live-simulation-tests-staging-cloud-run"]
    assert staging_deploy["env"]["CLOUD_RUN_SERVICE"] == STAGING_CLOUD_RUN_SERVICE
    assert production_deploy["env"]["CLOUD_RUN_SERVICE"] == (
        PRODUCTION_CLOUD_RUN_SERVICE
    )
    # The live tests call the staging deploy job's candidate.
    assert "deploy-cloud-run-staging" in str(live_tests["needs"])
    assert "deploy-cloud-run-candidate" not in str(live_tests["needs"])


def test_no_other_job_reads_the_ci_server_credential() -> None:
    readers = {
        (workflow_name, job_id)
        for workflow_name, workflow in _workflows().items()
        for job_id, job in workflow["jobs"].items()
        if "CI_SERVER_" in yaml.safe_dump(job)
    }

    assert readers == set(DEPLOYED_API_CALLERS)


def test_no_pull_request_workflow_reads_the_ci_server_credential() -> None:
    for workflow_name, workflow in _workflows().items():
        if _workflow_events(workflow) & PULL_REQUEST_EVENTS:
            workflow_text = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
            assert "CI_SERVER_" not in workflow_text, workflow_name
            assert "request_ci_server_token" not in workflow_text, workflow_name
