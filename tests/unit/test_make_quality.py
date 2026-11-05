"""One command runs the quality checks, locally and in CI (api.quality.make-quality).

make quality applies ruff's fixes, then runs make quality-check, which runs
every mechanical check without changing files. pr.yml's quality-guards job runs
make quality and fails if the fixes changed a file, so CI gets the result an
agent gets locally. No other pr.yml job runs one of those checks itself, so
the two can't drift apart. diff-cover isn't part of it: it needs every test
shard's coverage report, so pr.yml runs it in a job of its own.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from scripts.rules.makefile import make_recipes

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "rules" / "fixtures" / "api.quality.make-quality"
PR_WORKFLOW = REPO / ".github" / "workflows" / "pr.yml"
LOCKED = "uv run --frozen --extra dev"
FIXES = [f"{LOCKED} ruff check --fix .", f"{LOCKED} ruff format ."]
CHECKS = (
    "uv lock --check",
    f"{LOCKED} ruff check .",
    f"{LOCKED} ruff format --check .",
    f"{LOCKED} lint-imports --config pyproject.toml",
    f"{LOCKED} mypy",
    f"{LOCKED} python scripts/run_quality_guards.py",
)
# The tools that pr.yml may run only through make quality.
CHECK_TOOLS = ("ruff ", "mypy", "lint-imports", "run_quality_guards.py")
JOB = "quality-guards"


def quality_problems(makefile: str, workflow: str) -> list[str]:
    """Return how a Makefile and pr.yml break api.quality.make-quality."""
    recipes = make_recipes(makefile)
    problems = []
    if recipes.get("quality") != ([], [*FIXES, "$(MAKE) quality-check"]):
        problems.append(
            "make quality must run ruff's two fixes, then $(MAKE) quality-check"
        )
    check_commands = recipes.get("quality-check", ([], []))[1]
    problems += [
        f"make quality-check doesn't run '{check}'"
        for check in CHECKS
        if check not in check_commands
    ]
    problems += [
        f"make quality-check changes files: '{command}'"
        for command in check_commands
        if "--fix" in command or command == FIXES[1]
    ]
    jobs = yaml.safe_load(workflow)["jobs"]
    runs = [step.get("run", "") for step in jobs.get(JOB, {}).get("steps", [])]
    if (
        "make quality" not in runs
        or "git diff --exit-code" not in runs[runs.index("make quality") + 1 :]
    ):
        problems.append(
            f"pr.yml's {JOB} job must run make quality, then git diff --exit-code"
        )
    for name, job in jobs.items():
        text = "\n".join(step.get("run", "") for step in job.get("steps", []))
        problems += [
            f"pr.yml's {name} job runs {tool.strip()} itself"
            for tool in CHECK_TOOLS
            if tool in text
        ]
    if JOB not in jobs.get("ci-complete", {}).get("needs", []):
        problems.append(f"CI complete doesn't need {JOB}")
    return problems


def _fixture_problems(name: str) -> list[str]:
    return quality_problems(
        (FIXTURES / name / "Makefile").read_text(encoding="utf-8"),
        (FIXTURES / name / "pr.yml").read_text(encoding="utf-8"),
    )


def test_rule_proof_make_quality():
    assert _fixture_problems("rejected") == [
        f"make quality-check doesn't run '{LOCKED} mypy'",
        "pr.yml's typecheck job runs mypy itself",
    ]
    assert _fixture_problems("accepted") == []


def test_make_quality_runs_every_check_and_ci_runs_it():
    assert (
        quality_problems(
            (REPO / "Makefile").read_text(encoding="utf-8"),
            PR_WORKFLOW.read_text(encoding="utf-8"),
        )
        == []
    )


def test_the_quality_job_can_run_every_check():
    job = yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))["jobs"][JOB]
    steps = job["steps"]
    (checkout,) = [step for step in steps if "actions/checkout" in step.get("uses", "")]
    (uv,) = [step for step in steps if "setup-uv" in step.get("uses", "")]
    runs = [step.get("run", "") for step in steps]

    # The rules registry guard compares baselines with the base branch.
    assert checkout["with"]["fetch-depth"] == 0
    # The uv version the Cloud Run image and the release job use, so
    # `uv lock --check` reads uv.lock as they write it.
    assert uv["with"]["version"] == "0.13.4"
    assert job["env"]["UV_PYTHON"] == "3.12"
    # The ci-scripts guard runs shellcheck, and fails in CI without it.
    assert any("shellcheck-py" in run for run in runs)
    # The registry tool's own tests still run there.
    assert f"{LOCKED} python -m unittest discover -s scripts/rules/tests -t ." in runs
