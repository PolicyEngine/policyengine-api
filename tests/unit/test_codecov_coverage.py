"""Codecov measures the same tests on master as on pull requests.

Rule api.quality.coverage-measured: every CI job that measures test coverage
sends it to Codecov with a flag that codecov.yml carries forward, through the
CODECOV_TOKEN secret, and an upload in a master run fails the run when it
fails. make test (pr.yml's test job and push.yml's release-tests) uploads
``unit``; the cross-database integration tests upload ``integration``.

With both flags carried forward, a commit that uploads one flag carries the
other forward from its Codecov parent, a git parent with a Codecov report. A
master merge commit, which uploads only ``integration``, gets ``unit`` from
the pull request head or the master commit before it; its release commit,
which uploads ``unit`` measured on the merged code, gets ``integration`` from
the merge commit. No job waits for an upload, so a Codecov outage can't stop
a release: a reusable workflow hands its report to its caller as an artifact.
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
DEFAULT_ARTIFACT_NAME = "artifact"
TOKEN = "${{ secrets.CODECOV_TOKEN }}"
UNIT = "unit"
INTEGRATION = "integration"
REQUIRED_FLAGS = (UNIT, INTEGRATION)
REQUIRED_IGNORES = ("tests/**", "migrations/*/versions/**")
MAX_PROJECT_THRESHOLD_PERCENT = 1.0
# Commands that run the whole test suite, which writes coverage.xml, and
# commands that write some other coverage report.
SUITE_COMMAND = re.compile(r"\bmake test(?![-\w])|\brun_release_tests\.sh\b")
COVERAGE_COMMAND = re.compile(r"\bcoverage xml\b|--cov\b")
MATRIX_EXPRESSION = re.compile(r"\$\{\{\s*matrix\.(?P<key>[\w-]+)\s*\}\}")
REGEX_CHARACTERS = frozenset("*?[]()^$+|\\")
REUSABLE_UPLOAD = (
    "uploads coverage in a reusable workflow; keep the report as an artifact for "
    "a job in the calling workflow to upload"
)


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


def _inputs(step: dict) -> dict:
    return step.get("with") or {}


def _steps_using(job: dict, action: str) -> list[dict]:
    return [
        step
        for step in job.get("steps") or []
        if step.get("uses", "").startswith(action)
    ]


def _commands(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps") or [])


def _report_artifacts(job: dict, *, suite: bool) -> list[str]:
    """Return the names of the coverage reports a job keeps as artifacts."""
    return [
        _inputs(step).get("name", DEFAULT_ARTIFACT_NAME)
        for step in _steps_using(job, UPLOAD_ARTIFACT)
        if (
            _inputs(step).get("path") == "coverage.xml"
            if suite
            else str(_inputs(step).get("path", "")).endswith(".xml")
        )
    ]


def _artifact_names(template: str, job: dict) -> list[str]:
    """Return the artifact names a template gives for each matrix value."""
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    names = [template]
    for key in MATRIX_EXPRESSION.findall(template):
        values = matrix.get(key) if isinstance(matrix, dict) else None
        values = values if isinstance(values, list) else ["1"]
        names = [
            re.sub(rf"\$\{{\{{\s*matrix\.{key}\s*\}}\}}", str(value), name)
            for name in names
            for value in values
        ]
    return names


def _downloads(job: dict, name: str) -> bool:
    """Whether ``job`` downloads the artifact called ``name``."""
    for step in _steps_using(job, DOWNLOAD_ARTIFACT):
        inputs = _inputs(step)
        if "pattern" in inputs and fnmatch.fnmatch(name, inputs["pattern"]):
            return True
        if "name" in inputs and inputs["name"] == name:
            return True
        if "pattern" not in inputs and "name" not in inputs:
            return True
    return False


def _uploads_flag(job: dict, flag: str | None) -> bool:
    return any(
        _inputs(step).get("flags") == flag
        if flag is not None
        else bool(_inputs(step).get("flags"))
        for step in _steps_using(job, CODECOV_ACTION)
    )


def carried_forward_flags(config: dict, root: Path = REPO) -> dict[str, list[str]]:
    """Return each flag codecov.yml carries forward, with its problems.

    A flag is carried forward when it sets ``carryforward: true``, or leaves it
    to ``default_rules``. Its paths must be directories that exist.
    """
    management = config.get("flag_management") or {}
    default = (management.get("default_rules") or {}).get("carryforward") is True
    flags: dict[str, list[str]] = {}
    for flag in management.get("individual_flags") or []:
        carried = flag.get("carryforward", default) is True
        paths = flag.get("paths") or []
        if not (carried and paths):
            continue
        flags[flag["name"]] = [
            f"codecov.yml's {flag['name']} flag covers {path}, which doesn't exist"
            for path in paths
            if not REGEX_CHARACTERS & set(path) and not (root / path).exists()
        ]
    return flags


def config_problems(config: dict, root: Path = REPO) -> list[str]:
    """Report what codecov.yml lacks: flags, statuses or ignored paths."""
    flags = carried_forward_flags(config, root)
    problems = []
    for flag in REQUIRED_FLAGS:
        if flag not in flags:
            problems.append(
                f"codecov.yml has no {flag} flag with paths and carryforward: true"
            )
        else:
            problems.extend(flags[flag])
    statuses = (config.get("coverage") or {}).get("status") or {}
    project = (statuses.get("project") or {}).get("default") or {}
    threshold = str(project.get("threshold", "")).rstrip("%")
    try:
        small = 0 <= float(threshold) <= MAX_PROJECT_THRESHOLD_PERCENT
    except ValueError:
        small = False
    if not small:
        problems.append(
            "codecov.yml's project status has no threshold of at most "
            f"{MAX_PROJECT_THRESHOLD_PERCENT}%"
        )
    if not isinstance(statuses.get("patch"), dict):
        problems.append("codecov.yml has no patch status")
    ignored = config.get("ignore") or []
    problems.extend(
        f"codecov.yml doesn't ignore {path}"
        for path in REQUIRED_IGNORES
        if path not in ignored
    )
    return problems


def _upload_problems(
    name: str, job_id: str, jobs: dict, triggers: set[str], flags: set[str]
) -> list[str]:
    """Report what is wrong with a job's Codecov uploads."""
    where = f"{name}:{job_id}"
    job = jobs[job_id]
    problems = []
    for step in _steps_using(job, CODECOV_ACTION):
        inputs = _inputs(step)
        if inputs.get("flags") not in flags:
            problems.append(
                f"{where} uploads coverage without a flag codecov.yml carries forward"
            )
        if inputs.get("token") != TOKEN:
            problems.append(
                f"{where} doesn't pass the CODECOV_TOKEN secret as the token"
            )
        if "push" in triggers:
            ignored = job.get("continue-on-error") or step.get("continue-on-error")
            if inputs.get("fail_ci_if_error") is not True or ignored:
                problems.append(
                    f"{where} runs on master but a failed upload doesn't fail the run"
                )
            if "if" in job or "if" in step:
                problems.append(f"{where} can skip its upload on master")
        if "workflow_call" in triggers:
            problems.append(f"{where} {REUSABLE_UPLOAD}")
    if "push" in triggers and _steps_using(job, CODECOV_ACTION):
        problems.extend(
            f"{where} uploads coverage, and {other_id} waits for it"
            for other_id, other in jobs.items()
            if job_id in _needs(other)
        )
    return problems


def _callers(workflows: dict[str, dict], name: str) -> list[tuple[str, str]]:
    """Return ``(workflow, job)`` for each job that calls reusable workflow ``name``."""
    return [
        (caller, job_id)
        for caller, workflow in sorted(workflows.items())
        for job_id, job in (workflow.get("jobs") or {}).items()
        if str(job.get("uses", "")).endswith(f"/{name}")
    ]


def _report_problems(
    workflows: dict[str, dict], name: str, job_id: str, *, suite: bool
) -> list[str]:
    """Report a job's coverage report that no job uploads, every shard of it."""
    workflow = workflows[name]
    job = workflow["jobs"][job_id]
    artifacts = [
        artifact
        for template in _report_artifacts(job, suite=suite)
        for artifact in _artifact_names(template, job)
    ]
    report = "coverage.xml" if suite else "coverage report"
    if not artifacts:
        if suite:
            return [f"{name}:{job_id} runs the test suite but keeps no coverage.xml"]
        return [f"{name}:{job_id} measures coverage but uploads none"]
    if "workflow_call" in _triggers(workflow):
        places = _callers(workflows, name)
    else:
        places = [(name, job_id)]
    problems = []
    for place, waited_on in places:
        consumers = [
            consumer
            for consumer in (workflows[place].get("jobs") or {}).values()
            if waited_on in _needs(consumer)
            and _uploads_flag(consumer, UNIT if suite else None)
            and all(_downloads(consumer, artifact) for artifact in artifacts)
        ]
        if not consumers:
            flagged = f" flagged {UNIT}" if suite else ""
            problems.append(
                f"no job in {place} uploads all of {waited_on}'s {report}{flagged}"
            )
    if not places:
        problems.append(f"no workflow calls {name} to upload {job_id}'s {report}")
    return problems


def coverage_problems(
    workflows: dict[str, dict], config: dict, root: Path = REPO
) -> list[str]:
    """Report every way the workflows or codecov.yml could leave coverage unmeasured."""
    flags = set(carried_forward_flags(config, root))
    problems = config_problems(config, root)
    for name, workflow in sorted(workflows.items()):
        triggers = _triggers(workflow)
        jobs = workflow.get("jobs") or {}
        for job_id, job in jobs.items():
            uploads = _steps_using(job, CODECOV_ACTION)
            problems.extend(_upload_problems(name, job_id, jobs, triggers, flags))
            commands = _commands(job)
            if SUITE_COMMAND.search(commands):
                problems.extend(_report_problems(workflows, name, job_id, suite=True))
            elif COVERAGE_COMMAND.search(commands) and not uploads:
                problems.extend(_report_problems(workflows, name, job_id, suite=False))
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
        "integration.yml:integration uploads coverage without a flag codecov.yml "
        "carries forward",
        "integration.yml:integration uploads coverage in a reusable workflow; keep "
        "the report as an artifact for a job in the calling workflow to upload",
        "no job in pr.yml uploads all of test's coverage.xml flagged unit",
        "pr.yml:upload-test-coverage uploads coverage without a flag codecov.yml "
        "carries forward",
        "pr.yml:upload-test-coverage doesn't pass the CODECOV_TOKEN secret as the "
        "token",
        "pr.yml:integration measures coverage but uploads none",
        "push.yml:release-tests runs the test suite but keeps no coverage.xml",
        "push.yml:merge-upload uploads coverage without a flag codecov.yml carries "
        "forward",
        "push.yml:merge-upload runs on master but a failed upload doesn't fail the run",
        "push.yml:merge-upload uploads coverage, and deploy waits for it",
    ]
    assert accepted == []


GOOD_CONFIG = yaml.safe_load((FIXTURES / "accepted" / "codecov.yml").read_text())
SHARDED_SUITE = {
    "strategy": {"matrix": {"shard_index": [1, 2]}},
    "steps": [
        {"run": "make test"},
        {
            "uses": "actions/upload-artifact@v4",
            "with": {"name": "cov-${{ matrix.shard_index }}", "path": "coverage.xml"},
        },
    ],
}


def _upload_job(download: dict, *, needs: str = "test", **inputs: object) -> dict:
    return {
        "needs": needs,
        "steps": [
            {"uses": "actions/download-artifact@v4", "with": download},
            {
                "uses": "codecov/codecov-action@v5",
                "with": {"token": TOKEN, "flags": UNIT, **inputs},
            },
        ],
    }


def _master_upload(**job_fields: object) -> dict:
    upload = _upload_job({}, needs="build", fail_ci_if_error=True)
    upload.update(job_fields)
    return {
        "push.yml": {
            "on": {"push": {"branches": ["master"]}},
            "jobs": {"build": {"steps": [{"run": "echo"}]}, "upload": upload},
        }
    }


def test_every_shard_of_the_suite_must_be_uploaded():
    one_shard = {
        "pr.yml": {
            "on": "pull_request",
            "jobs": {
                "test": SHARDED_SUITE,
                "upload": _upload_job({"pattern": "cov-1"}),
            },
        }
    }
    every_shard = {
        "pr.yml": {
            "on": "pull_request",
            "jobs": {
                "test": SHARDED_SUITE,
                "upload": _upload_job({"pattern": "cov-*"}),
            },
        }
    }
    everything = {
        "pr.yml": {
            "on": "pull_request",
            "jobs": {"test": SHARDED_SUITE, "upload": _upload_job({})},
        }
    }

    assert coverage_problems(one_shard, GOOD_CONFIG) == [
        "no job in pr.yml uploads all of test's coverage.xml flagged unit"
    ]
    assert coverage_problems(every_shard, GOOD_CONFIG) == []
    assert coverage_problems(everything, GOOD_CONFIG) == []


def test_an_unnamed_artifact_and_similar_commands_are_read_correctly():
    unnamed = {
        "steps": [
            {"run": "make test"},
            {"uses": "actions/upload-artifact@v4", "with": {"path": "coverage.xml"}},
        ]
    }
    workflows = {
        "pr.yml": {
            "on": "pull_request",
            "jobs": {
                "test": unnamed,
                "upload": _upload_job({"name": "artifact"}),
                "env-vars": {"steps": [{"run": "make test-env-vars"}]},
                "pytest-cov": {"steps": [{"run": "pytest --cov=pkg --cov-report=xml"}]},
            },
        }
    }

    assert coverage_problems(workflows, GOOD_CONFIG) == [
        "pr.yml:pytest-cov measures coverage but uploads none"
    ]


def test_a_master_upload_that_can_be_skipped_or_ignored_fails_the_check():
    cases = {
        "a step that continues on error": {
            "steps": [
                {
                    "uses": "codecov/codecov-action@v5",
                    "continue-on-error": True,
                    "with": {"token": TOKEN, "flags": UNIT, "fail_ci_if_error": True},
                }
            ]
        },
        "a job that continues on error": {"continue-on-error": True},
        "a step with a condition": {
            "steps": [
                {
                    "uses": "codecov/codecov-action@v5",
                    "if": "github.event_name == 'schedule'",
                    "with": {"token": TOKEN, "flags": UNIT, "fail_ci_if_error": True},
                }
            ]
        },
        "a job with a condition": {"if": "false"},
    }
    expected = {
        "a step that continues on error": "push.yml:upload runs on master but a "
        "failed upload doesn't fail the run",
        "a job that continues on error": "push.yml:upload runs on master but a "
        "failed upload doesn't fail the run",
        "a step with a condition": "push.yml:upload can skip its upload on master",
        "a job with a condition": "push.yml:upload can skip its upload on master",
    }
    for case, job_fields in cases.items():
        workflows = _master_upload(**job_fields)
        assert coverage_problems(workflows, GOOD_CONFIG) == [expected[case]], case


def test_codecov_config_details():
    def problems_with(**changes: object) -> list[str]:
        config = yaml.safe_load((FIXTURES / "accepted" / "codecov.yml").read_text())
        for path, value in changes.items():
            *keys, last = path.split("__")
            target = config
            for key in keys:
                target = target[int(key)] if isinstance(target, list) else target[key]
            target[last] = value
        return config_problems(config)

    assert problems_with(coverage__status__patch="off") == [
        "codecov.yml has no patch status"
    ]
    assert problems_with(coverage__status__project__default__threshold="0%") == []
    assert problems_with(
        flag_management__individual_flags__0__paths=["policyengine/"]
    ) == ["codecov.yml's unit flag covers policyengine/, which doesn't exist"]
    default_rules = yaml.safe_load((FIXTURES / "accepted" / "codecov.yml").read_text())
    default_rules["flag_management"]["default_rules"] = {"carryforward": True}
    for flag in default_rules["flag_management"]["individual_flags"]:
        del flag["carryforward"]
    assert config_problems(default_rules) == []


def test_every_coverage_upload_is_flagged_and_master_uploads_fail_the_run():
    config = yaml.safe_load(CODECOV_CONFIG.read_text(encoding="utf-8"))

    assert coverage_problems(_load_workflows(WORKFLOWS), config) == []


def test_master_and_pull_requests_measure_both_flags():
    # The integration tests' workflow hands its report over as an artifact,
    # and a job of each caller uploads it: nothing in a release waits for
    # Codecov.
    workflows = _load_workflows(WORKFLOWS)

    assert _uploaded_flags(workflows["pr.yml"]) == {UNIT, INTEGRATION}
    assert _uploaded_flags(workflows["push.yml"]) == {UNIT, INTEGRATION}
    assert _uploaded_flags(workflows["v2-integration-check.yml"]) == set()
    for caller in ("pr.yml", "push.yml"):
        jobs = workflows[caller]["jobs"]
        integration = jobs["v2-integration-check"]
        assert integration["uses"] == "./.github/workflows/v2-integration-check.yml"
        assert "secrets" not in integration
        assert _needs(jobs["upload-integration-coverage"]) == ["v2-integration-check"]


def test_no_master_job_waits_for_a_codecov_upload():
    jobs = _load_workflows(WORKFLOWS)["push.yml"]["jobs"]
    uploads = {
        job_id for job_id, job in jobs.items() if _steps_using(job, CODECOV_ACTION)
    }

    assert uploads == {"upload-release-test-coverage", "upload-integration-coverage"}
    for job_id, job in jobs.items():
        assert not uploads & set(_needs(job)), job_id


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
