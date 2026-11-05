"""Codecov measures the same tests on master as on pull requests.

Rule api.quality.coverage-measured: every CI job that measures test coverage
sends it to Codecov with a flag that codecov.yml carries forward, through the
CODECOV_TOKEN secret, and an upload in a master run fails the run when it
fails. make test (pr.yml's test job and push.yml's release-tests) uploads
``unit``; the cross-database integration tests upload ``integration``.

With both flags carried forward, a master merge commit, which uploads only
``integration``, carries ``unit`` forward from its Codecov parent, the pull
request head; and the release commit, which uploads only ``unit``, carries
``integration`` forward from the merge commit. A pull request's project
coverage is then compared with a base that measured both.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
CODECOV_CONFIG = REPO / "codecov.yml"
FIXTURES = REPO / "rules" / "fixtures" / "api.quality.coverage-measured"
CODECOV_ACTION = "codecov/codecov-action@"
UPLOAD_ARTIFACT = "actions/upload-artifact@"
DOWNLOAD_ARTIFACT = "actions/download-artifact@"
TOKEN = "${{ secrets.CODECOV_TOKEN }}"
# A reusable workflow fails the run on an upload error only when its caller is
# a push to master.
FAIL_ON_PUSH = "${{ github.event_name == 'push' }}"
UNIT = "unit"
INTEGRATION = "integration"
REQUIRED_FLAGS = (UNIT, INTEGRATION)
REQUIRED_IGNORES = ("tests/**", "migrations/*/versions/**")
MAX_PROJECT_THRESHOLD_PERCENT = 1.0
# Commands that run the whole test suite, which writes coverage.xml.
SUITE_COMMANDS = ("make test", "run_release_tests.sh")
EXPRESSION = re.compile(r"\$\{\{.*?\}\}")


def _load_workflows(directory: Path) -> dict[str, dict]:
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.y*ml"))
    }


def _triggers(workflow: dict) -> set[str]:
    # PyYAML reads the key `on` as True.
    triggers = workflow.get("on", workflow.get(True))
    if isinstance(triggers, str):
        return {triggers}
    return set(triggers or ())


def _needs(job: dict) -> list[str]:
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


def _steps_using(job: dict, action: str) -> list[dict]:
    return [
        step
        for step in job.get("steps") or []
        if step.get("uses", "").startswith(action)
    ]


def _commands(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps") or [])


def _artifact_matches(pattern: str, name: str) -> bool:
    """Whether a download ``pattern`` matches an artifact ``name`` template."""
    return fnmatch.fnmatch(EXPRESSION.sub("1", name), pattern)


def carried_forward_flags(config: dict) -> set[str]:
    """Return the flags codecov.yml defines with paths and carryforward."""
    flags = (config.get("flag_management") or {}).get("individual_flags") or []
    return {
        flag["name"]
        for flag in flags
        if flag.get("carryforward") is True and flag.get("paths")
    }


def config_problems(config: dict) -> list[str]:
    """Report what codecov.yml lacks: flags, statuses or ignored paths."""
    problems = [
        f"codecov.yml has no {flag} flag with paths and carryforward: true"
        for flag in REQUIRED_FLAGS
        if flag not in carried_forward_flags(config)
    ]
    statuses = (config.get("coverage") or {}).get("status") or {}
    project = (statuses.get("project") or {}).get("default") or {}
    threshold = str(project.get("threshold", "")).rstrip("%")
    try:
        small = 0 < float(threshold) <= MAX_PROJECT_THRESHOLD_PERCENT
    except ValueError:
        small = False
    if not small:
        problems.append(
            "codecov.yml's project status has no threshold of at most "
            f"{MAX_PROJECT_THRESHOLD_PERCENT}%"
        )
    if "patch" not in statuses:
        problems.append("codecov.yml has no patch status")
    ignored = config.get("ignore") or []
    problems.extend(
        f"codecov.yml doesn't ignore {path}"
        for path in REQUIRED_IGNORES
        if path not in ignored
    )
    return problems


def _upload_problems(
    name: str, job_id: str, step: dict, triggers: set[str], flags: set[str]
) -> list[str]:
    where = f"{name}:{job_id}"
    inputs = step.get("with") or {}
    problems = []
    if inputs.get("flags") not in flags:
        problems.append(
            f"{where} uploads coverage without a flag codecov.yml carries forward"
        )
    if inputs.get("token") != TOKEN:
        problems.append(f"{where} doesn't pass the CODECOV_TOKEN secret as the token")
    failing = inputs.get("fail_ci_if_error")
    if "push" in triggers and failing is not True:
        problems.append(
            f"{where} runs on master but a failed upload doesn't fail the run"
        )
    if "workflow_call" in triggers and failing not in (True, FAIL_ON_PUSH):
        problems.append(
            f"{where} runs in master runs but a failed upload doesn't fail them"
        )
    return problems


def _suite_upload_problems(name: str, job_id: str, jobs: dict) -> list[str]:
    """Report a test-suite job whose coverage.xml no job uploads flagged unit."""
    job = jobs[job_id]
    artifacts = [
        step["with"]["name"]
        for step in _steps_using(job, UPLOAD_ARTIFACT)
        if (step.get("with") or {}).get("path") == "coverage.xml"
    ]
    if not artifacts:
        return [f"{name}:{job_id} runs the test suite but keeps no coverage.xml"]
    for other in jobs.values():
        inputs = [
            step.get("with") or {} for step in _steps_using(other, DOWNLOAD_ARTIFACT)
        ]
        downloads = [found.get("pattern") or found.get("name", "") for found in inputs]
        uploads_unit = any(
            (step.get("with") or {}).get("flags") == UNIT
            for step in _steps_using(other, CODECOV_ACTION)
        )
        downloads_report = any(
            _artifact_matches(pattern, artifact)
            for pattern in downloads
            for artifact in artifacts
        )
        if job_id in _needs(other) and uploads_unit and downloads_report:
            return []
    return [f"no job in {name} uploads {job_id}'s coverage.xml flagged {UNIT}"]


def coverage_problems(workflows: dict[str, dict], config: dict) -> list[str]:
    """Report every way the workflows or codecov.yml could leave coverage unmeasured."""
    flags = carried_forward_flags(config)
    problems = config_problems(config)
    for name, workflow in sorted(workflows.items()):
        triggers = _triggers(workflow)
        jobs = workflow.get("jobs") or {}
        for job_id, job in jobs.items():
            uploads = _steps_using(job, CODECOV_ACTION)
            for step in uploads:
                problems.extend(_upload_problems(name, job_id, step, triggers, flags))
            commands = _commands(job)
            if any(command in commands for command in SUITE_COMMANDS):
                problems.extend(_suite_upload_problems(name, job_id, jobs))
            elif "coverage xml" in commands and not uploads:
                problems.append(f"{name}:{job_id} measures coverage but uploads none")
    return problems


def _uploaded_flags(workflow: dict) -> set[str]:
    return {
        (step.get("with") or {}).get("flags")
        for job in (workflow.get("jobs") or {}).values()
        for step in _steps_using(job, CODECOV_ACTION)
    }


def test_rule_proof_coverage_measured():
    rejected = coverage_problems(
        _load_workflows(FIXTURES / "rejected" / "workflows"),
        yaml.safe_load((FIXTURES / "rejected" / "codecov.yml").read_text()),
    )
    accepted = coverage_problems(
        _load_workflows(FIXTURES / "accepted" / "workflows"),
        yaml.safe_load((FIXTURES / "accepted" / "codecov.yml").read_text()),
    )

    assert rejected == [
        "codecov.yml has no unit flag with paths and carryforward: true",
        "codecov.yml has no integration flag with paths and carryforward: true",
        "codecov.yml's project status has no threshold of at most 1.0%",
        "codecov.yml has no patch status",
        "codecov.yml doesn't ignore tests/**",
        "codecov.yml doesn't ignore migrations/*/versions/**",
        "no job in pr.yml uploads test's coverage.xml flagged unit",
        "pr.yml:upload-test-coverage uploads coverage without a flag codecov.yml "
        "carries forward",
        "pr.yml:upload-test-coverage doesn't pass the CODECOV_TOKEN secret as the "
        "token",
        "pr.yml:integration measures coverage but uploads none",
        "push.yml:release-tests runs the test suite but keeps no coverage.xml",
        "push.yml:merge-upload uploads coverage without a flag codecov.yml carries "
        "forward",
        "push.yml:merge-upload runs on master but a failed upload doesn't fail the run",
    ]
    assert accepted == []


def test_every_coverage_upload_is_flagged_and_master_uploads_fail_the_run():
    config = yaml.safe_load(CODECOV_CONFIG.read_text(encoding="utf-8"))

    assert coverage_problems(_load_workflows(WORKFLOWS), config) == []


def test_master_and_pull_requests_measure_both_flags():
    workflows = _load_workflows(WORKFLOWS)

    assert UNIT in _uploaded_flags(workflows["pr.yml"])
    assert UNIT in _uploaded_flags(workflows["push.yml"])
    assert _uploaded_flags(workflows["v2-integration-check.yml"]) == {INTEGRATION}
    for caller in ("pr.yml", "push.yml"):
        integration = workflows[caller]["jobs"]["v2-integration-check"]
        assert integration["uses"] == "./.github/workflows/v2-integration-check.yml"
        assert integration["secrets"] == {"CODECOV_TOKEN": TOKEN}


def test_master_uploads_the_release_tests_coverage_in_one_upload():
    # As pr.yml's upload-test-coverage does for the pull request shards, one
    # job sends the six release-test shards' reports to Codecov together.
    jobs = _load_workflows(WORKFLOWS)["push.yml"]["jobs"]
    release_tests = jobs["release-tests"]
    upload = jobs["upload-release-test-coverage"]
    (codecov_step,) = _steps_using(upload, CODECOV_ACTION)
    (download_step,) = _steps_using(upload, DOWNLOAD_ARTIFACT)

    assert _needs(upload) == ["release-tests"]
    assert not _steps_using(release_tests, CODECOV_ACTION)
    assert codecov_step["with"]["directory"] == download_step["with"]["path"]
    assert codecov_step["with"]["slug"] == "PolicyEngine/policyengine-api"
