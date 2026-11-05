"""One command runs the quality checks, locally and in CI (api.quality.make-quality).

make quality applies ruff's fixes, then runs make quality-check, which runs
every mechanical check without changing files. pr.yml's quality-guards job runs
make quality and fails if the fixes changed a file, so CI gets the result an
agent gets locally. No other pr.yml job runs one of those checks itself, so
the two can't drift apart. diff-cover isn't part of it: it needs every test
shard's coverage report, so pr.yml runs it in a job of its own.
"""

from __future__ import annotations

import os
import re
import subprocess
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
    # as push.yml runs them; and comparing baselines and rule statuses with
    # the commit the branch shares with its base branch (master locally).
    "RULES_BASE_REF=$$(git merge-base HEAD origin/$${GITHUB_BASE_REF:-master}) "
    f"{LOCKED} python -S scripts/run_quality_guards.py",
)
# The tools that pr.yml may run only through make quality.
CHECK_TOOLS = re.compile(r"\b(ruff|mypy|lint-imports|run_quality_guards\.py)\b")
# The quality job's steps, which may not be skipped or allowed to fail.
REQUIRED_STEPS = ("make quality", "git diff --exit-code HEAD")
JOB = "quality-guards"
# A command in make quality-check that changes files instead of checking them.
CHANGES_FILES = re.compile(r"--fix\b|\b(?:ruff format|uv lock)\b(?!.*--check)")
# Environment variables whose value can make make ignore failing commands.
MAKE_FLAG_VARIABLES = ("MAKEFLAGS", "MFLAGS")
# Variables of make's own that a test's make runs mustn't inherit.
MAKE_ENVIRONMENT = frozenset(
    {"MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEFILES", "MAKELEVEL"}
)


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
        if CHANGES_FILES.search(command)
    ]
    settings = yaml.safe_load(workflow)
    jobs = settings["jobs"]
    job = jobs.get(JOB, {})
    steps = job.get("steps", [])
    runs = [step.get("run", "") for step in steps]
    first = runs.index(REQUIRED_STEPS[0]) if REQUIRED_STEPS[0] in runs else None
    if first is None or runs[first + 1 : first + 2] != [REQUIRED_STEPS[1]]:
        problems.append(
            f"pr.yml's {JOB} job must run make quality, then "
            f"{REQUIRED_STEPS[1]} right after it"
        )
    environments = [
        ("pr.yml", settings.get("env") or {}),
        (f"pr.yml's {JOB} job", job.get("env") or {}),
        *(
            (f"pr.yml's '{step['run']}' step", step.get("env") or {})
            for step in steps
            if step.get("run") in REQUIRED_STEPS
        ),
    ]
    problems += [
        f"{where} sets {name}, which can make make ignore failing commands"
        for where, environment in environments
        for name in MAKE_FLAG_VARIABLES
        if name in environment
    ]
    if "continue-on-error" in job:
        problems.append(f"pr.yml's {JOB} job ignores its failures (continue-on-error)")
    problems += [
        f"pr.yml's {JOB} job may skip or ignore '{step['run']}'"
        for step in job.get("steps", [])
        if step.get("run") in REQUIRED_STEPS
        and any(key in step for key in ("if", "continue-on-error", "shell"))
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


# A stand-in for uv that records each call and fails the one named in
# UV_STUB_FAIL_ON, so make quality can be run for real without the checks.
STUB_UV = """#!/bin/sh
printf '%s\\n' "$*" >> "$UV_STUB_LOG"
if [ "$*" = "$UV_STUB_FAIL_ON" ]; then
  exit 1
fi
exit 0
"""


def _uv_arguments(command: str) -> str:
    """Return what a Makefile command passes to uv: ``run ...`` or ``lock ...``."""
    return command.split("uv ", 1)[1]


def make_quality_behavior_problems(makefile: str, directory: Path) -> list[str]:
    """Run make quality with a stand-in uv; return how it hides a failing check.

    Whatever the Makefile does, make quality must run the fixes and every check
    in order when they pass, and fail when any one of them fails.
    """
    (directory / "Makefile").write_text(makefile)
    stubs = directory / "stubs"
    stubs.mkdir(exist_ok=True)
    (stubs / "uv").write_text(STUB_UV)
    (stubs / "uv").chmod(0o755)
    log = directory / "uv.log"
    expected = [_uv_arguments(command) for command in (*FIXES, *CHECKS)]
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in MAKE_ENVIRONMENT
    }
    environment["PATH"] = f"{stubs}{os.pathsep}{environment.get('PATH', '')}"
    environment["UV_STUB_LOG"] = str(log)

    def run(fail_on: str) -> tuple[int, list[str]]:
        log.write_text("")
        result = subprocess.run(
            ["make", "--no-print-directory", "quality"],
            cwd=directory,
            env={**environment, "UV_STUB_FAIL_ON": fail_on},
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, log.read_text().splitlines()

    problems = []
    returncode, calls = run("")
    if returncode != 0 or calls != expected:
        problems.append(
            f"make quality, with every check passing, exited {returncode} and "
            f"ran {calls}, not {expected}"
        )
    for arguments in expected:
        returncode, _ = run(arguments)
        if returncode == 0:
            problems.append(f"make quality passes although 'uv {arguments}' fails")
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
DIFF_STEP = "      - run: git diff --exit-code HEAD\n"


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
        pytest.param(
            ACCEPTED_MAKEFILE,
            "env:\n  MAKEFLAGS: -i\n" + ACCEPTED_WORKFLOW,
            "MAKEFLAGS",
            id="MAKEFLAGS for the workflow",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                "  quality-guards:\n",
                "  quality-guards:\n    env:\n      MAKEFLAGS: -i\n",
            ),
            "MAKEFLAGS",
            id="MAKEFLAGS for the job",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                MAKE_QUALITY_STEP,
                MAKE_QUALITY_STEP + "        env:\n          MAKEFLAGS: -i\n",
            ),
            "MAKEFLAGS",
            id="MAKEFLAGS for the step",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                MAKE_QUALITY_STEP, MAKE_QUALITY_STEP + "        shell: bash {0}\n"
            ),
            "may skip or ignore 'make quality'",
            id="step shell",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                DIFF_STEP, "      - run: git add -A\n" + DIFF_STEP
            ),
            "must run make quality, then git diff --exit-code HEAD",
            id="a step between make quality and git diff",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE.replace(
                "\tuv lock --check\n", "\tuv lock\n\tuv lock --check\n"
            ),
            ACCEPTED_WORKFLOW,
            "changes files: 'uv lock'",
            id="quality-check relocks",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE + "\nquality-check: ; @true\n",
            ACCEPTED_WORKFLOW,
            "after ';'",
            id="a recipe after a semicolon replaces the checks",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            "defaults:\n  run:\n    shell: true {0}\n" + ACCEPTED_WORKFLOW,
            "defaults",
            id="a default shell for the workflow",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                "  quality-guards:\n",
                "  quality-guards:\n"
                "    defaults:\n      run:\n        shell: true {0}\n",
            ),
            "defaults",
            id="a default shell for the job",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                MAKE_QUALITY_STEP,
                '      - run: echo "MAKEFLAGS=-i" >> "$GITHUB_ENV"\n'
                + MAKE_QUALITY_STEP,
            ),
            "GITHUB_ENV",
            id="an earlier step sets the environment",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                "  quality-guards:\n",
                "  quality-guards:\n    env:\n      GNUMAKEFLAGS: -i\n",
            ),
            "GNUMAKEFLAGS",
            id="GNUMAKEFLAGS for the job",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                "  quality-guards:\n",
                "  quality-guards:\n    env:\n      MAKEFILES: ci.mk\n",
            ),
            "MAKEFILES",
            id="MAKEFILES for the job",
        ),
        pytest.param(
            ACCEPTED_MAKEFILE,
            ACCEPTED_WORKFLOW.replace(
                MAKE_QUALITY_STEP,
                MAKE_QUALITY_STEP + "        working-directory: docs\n",
            ),
            "may skip or ignore 'make quality'",
            id="another working directory",
        ),
    ],
)
def test_ways_to_skip_or_ignore_a_check_are_rejected(makefile, workflow, problem):
    problems = quality_problems(makefile, workflow)

    assert any(problem in reported for reported in problems), problems


@pytest.mark.parametrize(
    "setting",
    [
        pytest.param(".IGNORE::\n", id="double-colon .IGNORE"),
        pytest.param("GNUMAKEFLAGS += -i\n", id="GNUMAKEFLAGS"),
        pytest.param("M = MAKE\n$(M)FLAGS += -i\n", id="computed MAKEFLAGS"),
        pytest.param(
            "DRY_RUN := $(findstring n,$(firstword -$(MAKEFLAGS)))\n"
            "REAL_RUN_TARGET := $(if $(DRY_RUN),dry-run-only,quality-check)\n"
            "$(REAL_RUN_TARGET):\n"
            "\t@true\n",
            id="a recipe only for real runs",
        ),
    ],
)
def test_settings_that_hide_a_failing_check_are_rejected(setting, tmp_path):
    # Reading the Makefile reports what it recognizes; running make quality
    # with a failing check catches the rest, on whichever make honors them
    # (GNUMAKEFLAGS needs GNU make 4.0, which CI has).
    makefile = ACCEPTED_MAKEFILE + setting
    problems = quality_problems(
        makefile, ACCEPTED_WORKFLOW
    ) + make_quality_behavior_problems(makefile, tmp_path)

    assert problems


def test_make_quality_fails_whenever_a_check_fails(tmp_path):
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    assert make_quality_behavior_problems(makefile, tmp_path) == []


def test_make_itself_runs_the_listed_commands():
    # The Makefile reader follows a subset of make. make -n prints what make
    # would run, in CI's environment, so make itself must agree with it.
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}
    }
    environment["GITHUB_ACTIONS"] = "true"
    printed = subprocess.run(
        ["make", "-n", "--no-print-directory", "quality"],
        cwd=REPO,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    # make -n also prints the recursive call, as its own path to make.
    commands = [line for line in printed if not line.endswith("make quality-check")]
    assert commands == [command.replace("$$", "$") for command in (*FIXES, *CHECKS)]


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
