"""The lines a pull request changes are covered by tests (api.quality.diff-coverage).

pr.yml's diff-coverage job downloads the six test shards' coverage.xml files
and the cross-database integration tests' report, and runs diff-cover against
the pull request's base commit. diff-cover fails when less than the minimum of
the changed lines in measured files (policyengine_api, .coveragerc's source)
ran, counting a line as covered if any report covers it. CI complete needs the
job, so a failure blocks the merge.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
RULE_ID = "api.quality.diff-coverage"
FIXTURES = REPO / "rules" / "fixtures" / RULE_ID
PR_WORKFLOW = REPO / ".github" / "workflows" / "pr.yml"
JOB = "diff-coverage"
MINIMUM_PERCENT = 80
DIFF_COVER = Path(sys.executable).parent / "diff-cover"
GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com"]


def _git(repo: Path, *arguments: str) -> None:
    subprocess.run(
        [*GIT, "-c", "commit.gpgsign=false", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _coverage_report(source: Path, hits: list[int]) -> str:
    lines = "".join(
        f'<line number="{number}" hits="{count}"/>'
        for number, count in enumerate(hits, start=1)
    )
    return (
        '<?xml version="1.0" ?><coverage version="7.0">'
        f"<sources><source>{source}</source></sources><packages>"
        '<package name="."><classes><class name="module.py" filename="module.py">'
        f"<lines>{lines}</lines></class></classes></package></packages></coverage>"
    )


def _run_diff_cover(fixture: Path, root: Path) -> subprocess.CompletedProcess[str]:
    """Commit a module, change it as ``fixture`` says, and run diff-cover on it."""
    spec = tomllib.loads(fixture.read_text(encoding="utf-8"))
    changed, covered = spec["changed_lines"], spec["covered_lines"]
    package = root / "pkg"
    package.mkdir(parents=True)
    module = package / "module.py"
    module.write_text("VALUE = 0\n")
    _git(root, "init", "--quiet")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "base")
    module.write_text(
        "VALUE = 0\n"
        + "".join(f"value_{index} = {index}\n" for index in range(changed))
    )
    _git(root, "commit", "--quiet", "-am", "change")
    hits = [1] + [1] * covered + [0] * (changed - covered)
    (root / "coverage.xml").write_text(_coverage_report(package, hits))
    return subprocess.run(
        [
            str(DIFF_COVER),
            "coverage.xml",
            "--compare-branch=HEAD~1",
            f"--fail-under={MINIMUM_PERCENT}",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _job() -> dict:
    return yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))["jobs"][JOB]


def _step(job: dict, name: str) -> dict:
    (step,) = [step for step in job["steps"] if step.get("name") == name]
    return step


def test_rule_proof_diff_coverage(tmp_path: Path):
    below = _run_diff_cover(FIXTURES / "below_threshold.toml", tmp_path / "below")
    at_minimum = _run_diff_cover(FIXTURES / "at_threshold.toml", tmp_path / "at")

    assert below.returncode != 0, below.stdout
    assert "Coverage: 70%" in below.stdout
    assert at_minimum.returncode == 0, at_minimum.stdout
    assert "Coverage: 80%" in at_minimum.stdout


def test_pull_requests_check_the_coverage_of_their_changed_lines():
    workflow = yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"][JOB]
    checkout = _step(job, "Checkout repo")
    shards = _step(job, "Download every test shard's coverage report")
    integration = _step(job, "Download the integration coverage report")
    check = _step(job, "Check the coverage of the changed lines")

    # It runs after both kinds of tests, with no condition of its own: on a
    # stacked pull request above the lowest one they are skipped, so it is
    # skipped too, and CI complete fails there as it already does.
    assert sorted(job["needs"]) == ["test", "v2-integration-check"]
    assert "if" not in job
    assert JOB in workflow["jobs"]["ci-complete"]["needs"]
    assert 0 < job["timeout-minutes"] <= 15
    assert job["env"] == {"UV_PYTHON": "3.12"}
    # diff-cover compares with the base commit, which a shallow clone lacks.
    assert checkout["with"]["fetch-depth"] == 0
    assert shards["with"]["pattern"] == "test-coverage-shard-*"
    assert integration["with"]["name"] == "integration-coverage"
    reports = "${{ runner.temp }}/coverage"
    assert shards["with"]["path"] == reports
    assert integration["with"]["path"] == f"{reports}/integration-coverage"
    assert check["env"] == {"BASE_SHA": "${{ github.event.pull_request.base.sha }}"}
    assert check["run"] == (
        "uv run --frozen --extra dev diff-cover "
        '"$RUNNER_TEMP"/coverage/*/coverage*.xml '
        f'--compare-branch="$BASE_SHA" --fail-under={MINIMUM_PERCENT}'
    )


def test_the_minimum_is_the_same_in_the_rule_and_codecov():
    registry = tomllib.loads((REPO / "rules" / "registry.toml").read_text())
    (rule,) = [rule for rule in registry["rule"] if rule["id"] == RULE_ID]
    codecov = yaml.safe_load((REPO / "codecov.yml").read_text(encoding="utf-8"))
    patch = codecov["coverage"]["status"]["patch"]["default"]

    assert f"at least {MINIMUM_PERCENT}%" in rule["statement"]
    assert rule["proof"]["threshold"] == MINIMUM_PERCENT
    # Codecov's patch status shows the same minimum, without blocking.
    assert patch["target"] == f"{MINIMUM_PERCENT}%"
    assert patch["informational"] is True


def test_diff_cover_is_a_locked_development_dependency():
    project = tomllib.loads((REPO / "pyproject.toml").read_text())
    lock = tomllib.loads((REPO / "uv.lock").read_text())

    assert any(
        requirement.startswith("diff-cover")
        for requirement in project["project"]["optional-dependencies"]["dev"]
    )
    assert "diff-cover" in {package["name"] for package in lock["package"]}
