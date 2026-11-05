"""The lines a pull request changes are covered by tests (api.quality.diff-coverage).

pr.yml's diff-coverage job downloads the six test shards' coverage.xml files
and the cross-database integration tests' report, and runs diff-cover against
the first parent of the merge commit CI checks out: the base branch the pull
request merges into. diff-cover fails when less than the minimum of the changed
lines in measured files (policyengine_api, .coveragerc's source) ran, counting
a line as covered if any report covers it. CI complete needs the job, so a
failure blocks the merge.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
RULE_ID = "api.quality.diff-coverage"
FIXTURES = REPO / "rules" / "fixtures" / RULE_ID
PR_WORKFLOW = REPO / ".github" / "workflows" / "pr.yml"
COVERAGE_CONFIG = REPO / ".coveragerc"
JOB = "diff-coverage"
CHECK_STEP = "Check the coverage of the changed lines"
MINIMUM_PERCENT = 80
DIFF_COVER = Path(sys.executable).parent / "diff-cover"
LOCKED_DIFF_COVER = "uv run --frozen --extra dev diff-cover"
# The pull_request event's base.sha, which the job's step may read.
BASE_SHA_EXPRESSION = "${{ github.event.pull_request.base.sha }}"
GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com"]


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        [*GIT, "-c", "commit.gpgsign=false", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _coverage_report(source: Path, files: dict[str, list[int]]) -> str:
    """Return a coverage.py XML report: each file's hits, from its first line."""
    classes = "".join(
        f'<class name="{name}" filename="{name}"><lines>'
        + "".join(
            f'<line number="{number}" hits="{count}"/>'
            for number, count in enumerate(hits, start=1)
        )
        + "</lines></class>"
        for name, hits in files.items()
    )
    return (
        '<?xml version="1.0" ?><coverage version="7.0">'
        f"<sources><source>{source}</source></sources><packages>"
        f'<package name="."><classes>{classes}</classes></package></packages>'
        "</coverage>"
    )


def _write_lines(module: Path, count: int) -> None:
    module.write_text("".join(f"value_{index} = {index}\n" for index in range(count)))


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
    (root / "coverage.xml").write_text(_coverage_report(package, {"module.py": hits}))
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


def _merged_pull_request(root: Path) -> str:
    """Build the merge commit CI checks out; return where the branch left master.

    The pull request adds 10 lines in pkg/pull_request.py. After it left
    master, master gained 100 lines in pkg/master_change.py. HEAD merges the
    pull request into master as it is now, as GitHub's merge ref does.
    """
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "module.py").write_text("VALUE = 0\n")
    _git(root, "init", "--quiet", "--initial-branch=master")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "where the pull request starts")
    fork_point = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "--quiet", "-b", "pull-request")
    _write_lines(package / "pull_request.py", 10)
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "the pull request's change")
    _git(root, "checkout", "--quiet", "master")
    _write_lines(package / "master_change.py", 100)
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "master moves on")
    _git(root, "merge", "--quiet", "--no-ff", "--no-edit", "pull-request")
    return fork_point


def _run_job_check(
    repo: Path, reports: dict[str, str], base_sha: str
) -> subprocess.CompletedProcess[str]:
    """Run the job's check step in ``repo`` as CI does, with the locked diff-cover.

    ``reports`` maps each report's path under $RUNNER_TEMP/coverage, where the
    job's download steps put them, to its XML. ``base_sha`` is the
    pull_request event's base.sha, for a step that reads it.
    """
    runner_temp = repo.parent / "runner-temp"
    for relative_path, report in reports.items():
        path = runner_temp / "coverage" / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report)
    step = _step(_job(), CHECK_STEP)
    assert step["run"].startswith(f"{LOCKED_DIFF_COVER} ")
    command = shlex.quote(str(DIFF_COVER)) + step["run"].removeprefix(LOCKED_DIFF_COVER)
    step_environment = {
        name: value.replace(BASE_SHA_EXPRESSION, base_sha)
        for name, value in step.get("env", {}).items()
    }
    assert not any("${{" in value for value in step_environment.values())
    return subprocess.run(
        ["bash", "-e", "-c", command],
        cwd=repo,
        env={**os.environ, "RUNNER_TEMP": str(runner_temp), **step_environment},
        capture_output=True,
        text=True,
        check=False,
    )


def _run_coverage(cwd: Path, data_file: Path, *arguments: str) -> None:
    """Run coverage.py with the repository's .coveragerc."""
    subprocess.run(
        [sys.executable, "-m", "coverage", *arguments],
        cwd=cwd,
        env={**os.environ, "COVERAGE_FILE": str(data_file)},
        check=True,
        capture_output=True,
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
    assert "Coverage: 79%" in below.stdout
    assert at_minimum.returncode == 0, at_minimum.stdout
    assert "Coverage: 80%" in at_minimum.stdout


def test_the_job_measures_only_the_lines_the_pull_request_changes(tmp_path: Path):
    # The event's base.sha often stays where the branch left master, while CI
    # checks out a merge into master as it is now. Master's own changes since
    # then, 95% covered here, must not lift the pull request's 50%.
    repo = tmp_path / "repo"
    fork_point = _merged_pull_request(repo)
    report = _coverage_report(
        repo / "pkg",
        {
            "module.py": [1],
            "pull_request.py": [1] * 5 + [0] * 5,
            "master_change.py": [1] * 95 + [0] * 5,
        },
    )

    result = _run_job_check(
        repo, {"test-coverage-shard-1/coverage.xml": report}, base_sha=fork_point
    )

    assert result.returncode != 0, result.stdout
    assert "Coverage: 50%" in result.stdout
    assert "master_change.py" not in result.stdout


def test_a_line_counts_as_covered_if_any_report_covers_it(tmp_path: Path):
    # A shard covers the first five changed lines and the integration tests
    # lines four to eight: 50% each, 80% together.
    repo = tmp_path / "repo"
    fork_point = _merged_pull_request(repo)
    shard = _coverage_report(repo / "pkg", {"pull_request.py": [1] * 5 + [0] * 5})
    integration = _coverage_report(
        repo / "pkg", {"pull_request.py": [0] * 3 + [1] * 5 + [0] * 2}
    )

    result = _run_job_check(
        repo,
        {
            "test-coverage-shard-1/coverage.xml": shard,
            "integration-coverage/coverage-v2.xml": integration,
        },
        base_sha=fork_point,
    )

    assert result.returncode == 0, result.stdout
    assert "Coverage: 80%" in result.stdout


def test_reports_match_the_changed_files_in_another_checkout(tmp_path: Path):
    # A report names each file by a source directory and the path below it.
    # An absolute source written in another checkout directory, such as a
    # container job's, matches no changed file, and diff-cover then passes with
    # "No lines with coverage information". The pull request adds an untested
    # function: one of its two changed lines runs.
    base = "VALUE = 0\n"
    head = base + "def untested():\n    return VALUE\n"
    measured = tmp_path / "measured"
    (measured / "policyengine_api").mkdir(parents=True)
    (measured / "policyengine_api" / "__init__.py").write_text("")
    (measured / "policyengine_api" / "module.py").write_text(head)
    (measured / "run.py").write_text("import policyengine_api.module\n")
    report = tmp_path / "coverage.xml"
    data_file = tmp_path / ".coverage"
    rcfile = f"--rcfile={COVERAGE_CONFIG}"
    _run_coverage(measured, data_file, "run", rcfile, "--branch", "run.py")
    _run_coverage(measured, data_file, "xml", rcfile, "-q", "-o", str(report))
    checked = tmp_path / "checked"
    (checked / "policyengine_api").mkdir(parents=True)
    (checked / "policyengine_api" / "__init__.py").write_text("")
    (checked / "policyengine_api" / "module.py").write_text(base)
    _git(checked, "init", "--quiet")
    _git(checked, "add", ".")
    _git(checked, "commit", "--quiet", "-m", "base")
    (checked / "policyengine_api" / "module.py").write_text(head)
    _git(checked, "commit", "--quiet", "-am", "the pull request's change")

    result = _run_job_check(
        checked,
        {"test-coverage-shard-1/coverage.xml": report.read_text()},
        base_sha="unused",
    )

    assert result.returncode != 0, result.stdout
    assert "Coverage: 50%" in result.stdout


def test_coverage_reports_every_module_no_test_imports(tmp_path: Path):
    # diff-cover only counts the files a report lists. coverage.py lists a
    # module no test imported only if every directory between it and the
    # source root has an __init__.py, so an untested module elsewhere under
    # policyengine_api would be left out, and its changed lines would pass.
    nothing = tmp_path / "nothing.py"
    nothing.write_text("")
    report = tmp_path / "coverage.json"
    data_file = tmp_path / ".coverage"
    rcfile = f"--rcfile={COVERAGE_CONFIG}"

    _run_coverage(REPO, data_file, "run", rcfile, str(nothing))
    _run_coverage(REPO, data_file, "json", rcfile, "-q", "-o", str(report))

    reported = set(json.loads(report.read_text())["files"])
    modules = {
        path.relative_to(REPO).as_posix()
        for path in (REPO / "policyengine_api").rglob("*.py")
    }
    assert sorted(modules - reported) == []


def test_type_only_imports_and_pragmas_are_not_counted_as_missed(tmp_path: Path):
    # Imports under `if TYPE_CHECKING:` never run, and ruff's TC rules move
    # imports there, so counting them would fail a fully tested change.
    # coverage.py's default `pragma: no cover` pattern keeps working too, in
    # each spelling it accepts.
    package = tmp_path / "policyengine_api"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "module.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from collections.abc import Iterator\n"
        "\n"
        "VALUE = 1\n"
        "\n"
        "\n"
        "def unused():  # pragma: no cover\n"
        "    return VALUE\n"
        "\n"
        "\n"
        "def also_unused():  #pragma:no cover\n"
        "    return VALUE\n"
        "\n"
        "\n"
        "def unused_too():  # PRAGMA NO COVER\n"
        "    return VALUE\n"
    )
    (tmp_path / "run.py").write_text("import policyengine_api.module\n")
    report = tmp_path / "coverage.json"
    data_file = tmp_path / ".coverage"
    rcfile = f"--rcfile={COVERAGE_CONFIG}"

    _run_coverage(tmp_path, data_file, "run", rcfile, "--branch", "run.py")
    _run_coverage(tmp_path, data_file, "json", rcfile, "-q", "-o", str(report))

    module = json.loads(report.read_text())["files"]["policyengine_api/module.py"]
    assert module["missing_lines"] == []
    assert {4, 10, 14, 18} <= set(module["excluded_lines"])


def test_pull_requests_check_the_coverage_of_their_changed_lines():
    workflow = yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"][JOB]
    checkout = _step(job, "Checkout repo")
    shards = _step(job, "Download every test shard's coverage report")
    integration = _step(job, "Download the integration coverage report")
    check = _step(job, CHECK_STEP)

    # It runs after both kinds of tests, with no condition of its own: on a
    # stacked pull request above the lowest one they are skipped, so it is
    # skipped too, and CI complete fails there as it already does.
    # HEAD^1 below is the base branch only in a pull_request event's merge
    # checkout. (PyYAML reads the `on` key as True.)
    assert workflow[True] == "pull_request"
    assert sorted(job["needs"]) == ["test", "v2-integration-check"]
    assert "if" not in job
    assert JOB in workflow["jobs"]["ci-complete"]["needs"]
    assert 0 < job["timeout-minutes"] <= 15
    assert job["env"] == {"UV_PYTHON": "3.12"}
    # diff-cover compares with the merge commit's first parent, which a
    # depth-1 clone lacks.
    assert checkout["with"]["fetch-depth"] == 0
    assert shards["with"]["pattern"] == "test-coverage-shard-*"
    assert integration["with"]["name"] == "integration-coverage"
    reports = "${{ runner.temp }}/coverage"
    assert shards["with"]["path"] == reports
    assert integration["with"]["path"] == f"{reports}/integration-coverage"
    # The checkout is GitHub's merge of the pull request into its base branch,
    # so HEAD^1 is the base branch the pull request merges into. The event's
    # base.sha can be older, which would count the base branch's own changes.
    assert "env" not in check
    assert check["run"] == (
        f"{LOCKED_DIFF_COVER} "
        '"$RUNNER_TEMP"/coverage/*/coverage*.xml '
        f"--compare-branch=HEAD^1 --fail-under={MINIMUM_PERCENT}"
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
