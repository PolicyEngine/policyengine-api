"""Tests that a rule's CI job really collects its test nodes and matrix project."""

from __future__ import annotations

import unittest

from scripts.rules.model import CiRef, Enforcer, Kind, Proof, Rule, Status, Tier
from scripts.rules.resolve import resolve_ci, resolve_proof_ci
from scripts.rules.tests.support import Repo

PR_WORKFLOW = ".github/workflows/pr.yml"
WORKFLOW = """
jobs:
  test:
    strategy:
      matrix:
        project: [projects/alpha, projects/beta]
    steps:
      - run: make test
  unit:
    steps:
      - run: python -m unittest discover -s tools/tests -t .
  unit-default:
    steps:
      - run: python -m unittest discover
  other:
    steps:
      - run: tox -e py
"""
MAKEFILE = (
    "test:\n"
    "\tpython -m pytest tests/unit tests/contract/test_a.py --disable-pytest-warnings\n"
)
MAKE_TEST = "'make test' (collects ['tests/unit', 'tests/contract/test_a.py'])"
UNITTEST = "'unittest discover -s tools/tests' (collects ['tools/tests'])"


def make_rule(
    fields: dict[str, object],
    ci: tuple[CiRef, ...] = (),
    proof: dict[str, object] | None = None,
    kind: Kind = Kind.PYTEST,
) -> Rule:
    return Rule(
        id="ex.r",
        category="checks",
        statement="A statement.",
        rationale="docs/guide.md",
        scope=("pkg/*.py",),
        tier=Tier.MECHANICAL,
        status=Status.ENFORCED,
        autofix=False,
        enforcer=Enforcer(kind, fields),
        ci=ci,
        proof=Proof(proof) if proof is not None else None,
    )


def not_collected(check: str, path: str, command: str) -> str:
    return (
        f"[ex.r] {check}: {path} is not collected by {command}. "
        "Fix: add it to what the job runs, or move the test."
    )


def not_in_matrix(check: str, project: str) -> str:
    return (
        f"[ex.r] {check}: project {project} is not in the matrix of job 'test'. "
        "Fix: add the project to the job matrix."
    )


class TestCoverageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo({PR_WORKFLOW: WORKFLOW, "Makefile": MAKEFILE}, render=False)
        self.addCleanup(self.repo.__exit__)

    def ci_messages(self, rule: Rule) -> list[str]:
        return [str(violation) for violation in resolve_ci(rule, self.repo.root)]

    def proof_messages(self, rule: Rule) -> list[str]:
        return [str(violation) for violation in resolve_proof_ci(rule, self.repo.root)]

    def test_make_target_must_collect_every_node(self) -> None:
        rule = make_rule(
            {
                "nodes": [
                    "tests/unit/test_a.py::t",
                    "tests/other/test_b.py::t",
                    "tests/contract/test_a.py",
                    "tests/unitx/test_c.py",
                ]
            },
            (CiRef(PR_WORKFLOW, "test", "make test"),),
        )
        self.assertEqual(
            self.ci_messages(rule),
            [
                not_collected("ci", "tests/other/test_b.py", MAKE_TEST),
                not_collected("ci", "tests/unitx/test_c.py", MAKE_TEST),
            ],
        )

    def test_project_must_be_in_the_job_matrix(self) -> None:
        missing = make_rule(
            {"project": "projects/gamma", "nodes": ["tests/test_g.py::t"]},
            (CiRef(PR_WORKFLOW, "test", "make test"),),
        )
        self.assertEqual(
            self.ci_messages(missing),
            [
                not_collected("ci", "projects/gamma/tests/test_g.py", MAKE_TEST),
                not_in_matrix("ci", "projects/gamma"),
            ],
        )
        listed = make_rule(
            {"project": "projects/alpha", "nodes": ["tests/test_g.py::t"]},
            (CiRef(PR_WORKFLOW, "test", "make test"),),
        )
        self.assertEqual(
            self.ci_messages(listed),
            [not_collected("ci", "projects/alpha/tests/test_g.py", MAKE_TEST)],
        )

    def test_unittest_start_directory_must_hold_every_node(self) -> None:
        rule = make_rule(
            {
                "nodes": [
                    "tools/tests/test_a.py::T::t",
                    "tools/testsx/test_b.py",
                    "other/test_c.py",
                ]
            },
            (CiRef(PR_WORKFLOW, "unit", "unittest discover -s tools/tests"),),
        )
        self.assertEqual(
            self.ci_messages(rule),
            [
                not_collected("ci", "tools/testsx/test_b.py", UNITTEST),
                not_collected("ci", "other/test_c.py", UNITTEST),
            ],
        )

    def test_other_commands_are_trusted(self) -> None:
        default_discovery = make_rule(
            {"nodes": ["other/test_c.py"]},
            (CiRef(PR_WORKFLOW, "unit-default", "unittest discover"),),
        )
        other_command = make_rule(
            {"project": "projects/gamma", "nodes": ["other/test_c.py"]},
            (CiRef(PR_WORKFLOW, "other", "tox"),),
        )
        self.assertEqual(self.ci_messages(default_discovery), [])
        self.assertEqual(self.ci_messages(other_command), [])

    def test_named_proof_job_must_collect_the_proof(self) -> None:
        rule = make_rule(
            {"paths": ["pkg"]},
            proof={
                "test": "elsewhere/test_p.py::t",
                "project": "projects/gamma/",
                "workflow": PR_WORKFLOW,
                "job": "test",
                "invocation": "make test",
            },
            kind=Kind.MYPY,
        )
        self.assertEqual(
            self.proof_messages(rule),
            [
                not_collected("proof", "projects/gamma/elsewhere/test_p.py", MAKE_TEST),
                not_in_matrix("proof", "projects/gamma/"),
            ],
        )

    def test_pytest_proof_runs_in_each_ci_job(self) -> None:
        rule = make_rule(
            {"nodes": ["tests/unit/test_a.py::t"]},
            (
                CiRef(PR_WORKFLOW, "unit", "unittest discover -s tools/tests"),
                CiRef(PR_WORKFLOW, "other", "tox"),
            ),
            proof={"test": "tests/unit/test_p.py::t"},
        )
        self.assertEqual(
            self.ci_messages(rule),
            [not_collected("ci", "tests/unit/test_a.py", UNITTEST)],
        )
        self.assertEqual(
            self.proof_messages(rule),
            [not_collected("proof", "tests/unit/test_p.py", UNITTEST)],
        )


if __name__ == "__main__":
    unittest.main()
