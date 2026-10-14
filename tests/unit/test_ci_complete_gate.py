"""Tests for the stacked-PR CI gate: pr.yml's shape and check_ci_complete.sh.

Only the lowest unmerged pull request in a stack runs the full PR workflow.
The "CI complete" job is the required check: it needs every other job, fails on
the pull requests above the bottom of a stack, and otherwise passes only when
every job passed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PR_WORKFLOW = REPO / ".github" / "workflows" / "pr.yml"
GATE_SCRIPT = ".github/scripts/check_ci_complete.sh"
GATE_JOB = "ci-complete"
GATE_CONDITION = "${{ always() }}"
FULL_CI_CONDITION = (
    "${{ !github.event.pull_request.stack || "
    "github.event.pull_request.stack.base.ref == github.event.pull_request.base.ref }}"
)


def gate_violations(workflow: dict) -> list[str]:
    """Return every way a job in ``workflow`` could escape the CI-complete gate."""
    jobs = workflow.get("jobs") or {}
    gate = jobs.get(GATE_JOB)
    if gate is None:
        return [f"the workflow has no {GATE_JOB} job"]

    violations = []
    if gate.get("if") != GATE_CONDITION:
        violations.append(f"{GATE_JOB} must have if: {GATE_CONDITION}")

    gated_jobs = gate.get("needs") or []
    if isinstance(gated_jobs, str):
        gated_jobs = [gated_jobs]
    violations.extend(
        f"{GATE_JOB} does not need {job_id}"
        for job_id in sorted(set(jobs) - {GATE_JOB} - set(gated_jobs))
    )

    for job_id, job in jobs.items():
        if job_id == GATE_JOB:
            continue
        condition = job.get("if")
        if job.get("needs"):
            # A job that needs a skipped job is skipped too, unless its own
            # condition overrides that.
            if condition is not None and condition != FULL_CI_CONDITION:
                violations.append(f"{job_id} has its own condition: {condition}")
        elif condition != FULL_CI_CONDITION:
            violations.append(f"{job_id} must have if: {FULL_CI_CONDITION}")
    return violations


def test_pr_workflow_is_gated() -> None:
    workflow = yaml.safe_load(PR_WORKFLOW.read_text())

    assert gate_violations(workflow) == []


def test_gate_check_rejects_an_ungated_job() -> None:
    workflow = {
        "jobs": {
            GATE_JOB: {"if": GATE_CONDITION, "needs": ["lint"]},
            "lint": {"if": FULL_CI_CONDITION},
            "test": {},
        }
    }

    assert gate_violations(workflow) == [
        f"{GATE_JOB} does not need test",
        f"test must have if: {FULL_CI_CONDITION}",
    ]


def test_rule_proof_gate_check() -> None:
    fixtures = REPO / "rules" / "fixtures" / "api.process.stacked-prs-full-ci-at-bottom"
    bad = yaml.safe_load((fixtures / "bad_pr.yml").read_text())
    good = yaml.safe_load((fixtures / "good_pr.yml").read_text())

    assert gate_violations(bad) == [
        f"{GATE_JOB} does not need test",
        f"test must have if: {FULL_CI_CONDITION}",
    ]
    assert gate_violations(good) == []


def _run_gate(
    job_results: dict[str, str],
    *,
    pull_request_base_ref: str = "master",
    stack_base_ref: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", GATE_SCRIPT],
        cwd=REPO,
        env={
            "HOME": os.environ.get("HOME", ""),
            "PATH": os.environ["PATH"],
            "JOB_RESULTS": json.dumps(
                {
                    job_id: {"result": result, "outputs": {}}
                    for job_id, result in job_results.items()
                }
            ),
            "PULL_REQUEST_BASE_REF": pull_request_base_ref,
            "STACK_BASE_REF": stack_base_ref,
        },
        text=True,
        capture_output=True,
        check=False,
    )


def test_gate_passes_an_unstacked_pull_request_when_every_job_passed() -> None:
    result = _run_gate({"lint": "success", "test": "success"})

    assert result.returncode == 0, result.stdout
    assert result.stdout == "Every job passed.\n"


def test_gate_passes_the_lowest_unmerged_pull_request_in_a_stack() -> None:
    result = _run_gate(
        {"lint": "success", "test": "success"},
        pull_request_base_ref="master",
        stack_base_ref="master",
    )

    assert result.returncode == 0, result.stdout


def test_gate_fails_a_pull_request_higher_in_a_stack() -> None:
    result = _run_gate(
        {"lint": "skipped", "test": "skipped"},
        pull_request_base_ref="ruff-annotations",
        stack_base_ref="master",
    )

    assert result.returncode == 1
    assert "lowest unmerged pull request in a stack" in result.stdout
    assert "targets ruff-annotations" in result.stdout


def test_gate_fails_and_names_every_job_that_did_not_pass() -> None:
    result = _run_gate(
        {"lint": "success", "test": "failure", "typecheck-v2": "cancelled"},
    )

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "::error::Job did not pass: test: failure",
        "::error::Job did not pass: typecheck-v2: cancelled",
    ]


def test_gate_fails_when_a_job_was_skipped_on_full_ci() -> None:
    result = _run_gate({"lint": "success", "test": "skipped"}, stack_base_ref="master")

    assert result.returncode == 1
    assert "::error::Job did not pass: test: skipped" in result.stdout


def test_gate_requires_the_job_results() -> None:
    result = subprocess.run(
        ["bash", GATE_SCRIPT],
        cwd=REPO,
        env={"PATH": os.environ["PATH"], "PULL_REQUEST_BASE_REF": "master"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "JOB_RESULTS is required" in result.stderr
