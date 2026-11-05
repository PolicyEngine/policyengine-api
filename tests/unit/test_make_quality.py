"""One command runs the quality checks, locally and in CI (api.quality.make-quality).

make quality applies ruff's fixes, then runs make quality-check, which runs
every mechanical check without changing files. pr.yml's quality-guards job runs
make quality and fails if the fixes changed a file, so CI gets the result an
agent gets locally. No other pr.yml job runs one of those checks itself, so
the two can't drift apart. diff-cover isn't part of it: it needs every test
shard's coverage report, so pr.yml runs it in a job of its own.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from scripts.rules.makefile import (
    job_make_targets,
    make_commands,
    make_recipes,
    makefile_problems,
)

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
    # Without site-packages (-S), so the guards keep to the standard library,
    # as push.yml runs them; and comparing baselines with the base branch,
    # as CI does, or with master locally.
    f"GITHUB_BASE_REF=$${{GITHUB_BASE_REF:-master}} {LOCKED} python -S "
    "scripts/run_quality_guards.py",
)
# The tools that pr.yml may run only through make quality.
CHECK_TOOLS = re.compile(r"\b(ruff|mypy|lint-imports|run_quality_guards\.py)\b")
# The quality job's steps, which may not be skipped or allowed to fail.
REQUIRED_STEPS = ("make quality", "git diff --exit-code")
JOB = "quality-guards"


def quality_problems(makefile: str, workflow: str) -> list[str]:
    """Return how a Makefile and pr.yml break api.quality.make-quality."""
    recipes = make_recipes(makefile)
    problems = [f"the Makefile {problem}" for problem in makefile_problems(makefile)]
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
    job = jobs.get(JOB, {})
    runs = [step.get("run", "") for step in job.get("steps", [])]
    if (
        "make quality" not in runs
        or "git diff --exit-code" not in runs[runs.index("make quality") + 1 :]
    ):
        problems.append(
            f"pr.yml's {JOB} job must run make quality, then git diff --exit-code"
        )
    if "continue-on-error" in job:
        problems.append(f"pr.yml's {JOB} job ignores its failures (continue-on-error)")
    problems += [
        f"pr.yml's {JOB} job may skip or ignore '{step['run']}'"
        for step in job.get("steps", [])
        if step.get("run") in REQUIRED_STEPS
        and ("if" in step or "continue-on-error" in step)
    ]
    for name, other in jobs.items():
        run_text = "\n".join(step.get("run", "") for step in other.get("steps", []))
        # The quality job runs the checks through make quality; any other
        # job that runs a make target runs that target's commands itself.
        commands = [
            run_text,
            *(
                []
                if name == JOB
                else make_commands(makefile, job_make_targets(run_text))
            ),
        ]
        tools = sorted(
            {
                match.group(1)
                for command in commands
                for match in CHECK_TOOLS.finditer(command)
            }
        )
        problems += [f"pr.yml's {name} job runs {tool} itself" for tool in tools]
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


ACCEPTED_MAKEFILE = (FIXTURES / "accepted" / "Makefile").read_text(encoding="utf-8")
ACCEPTED_WORKFLOW = (FIXTURES / "accepted" / "pr.yml").read_text(encoding="utf-8")
MAKE_QUALITY_STEP = "      - run: make quality\n"


@pytest.mark.parametrize(
    ("makefile", "workflow", "problem"),
    [
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                MAKE_QUALITY_STEP,
                MAKE_QUALITY_STEP + "        continue-on-error: true\n",
            ),
            "may skip or ignore 'make quality'",
            id="step continue-on-error",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                MAKE_QUALITY_STEP, MAKE_QUALITY_STEP + "        if: ${{ false }}\n"
            ),
            "may skip or ignore 'make quality'",
            id="step condition",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                "  quality-guards:\n",
                "  quality-guards:\n    continue-on-error: true\n",
            ),
            "ignores its failures",
            id="job continue-on-error",
        ),
        pytest.param(
            ".IGNORE: quality-check\n" + ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW,
            ".IGNORE",
            id="Makefile ignores failures",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE + "\ntypecheck:\n\tuv run --frozen --extra dev mypy\n",
            ACCEPTED_WORKFLOW
            + "  typecheck:\n    steps:\n      - run: make typecheck\n",
            "pr.yml's typecheck job runs mypy itself",
            id="another job runs a make target with a check",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW + "  format:\n    steps:\n      - run: pipx run ruff\n",
            "pr.yml's format job runs ruff itself",
            id="ruff at the end of a command",
        ),
    ],
)
def test_ways_to_skip_or_ignore_a_check_are_rejected(makefile, workflow, problem):
    problems = quality_problems(makefile, workflow)

    assert any(problem in reported for reported in problems), problems


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
