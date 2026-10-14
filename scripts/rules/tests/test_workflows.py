"""Tests for the GitHub Actions subset reader.

They are pinned against both repos' real PR workflows.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.rules.workflows import JobBlock, RunBlock, parse_jobs

FIXTURES = Path(__file__).parent / "fixtures"


class RealWorkflowTest(unittest.TestCase):
    def test_policyengine_api_pr_workflow(self) -> None:
        jobs, problems = parse_jobs((FIXTURES / "policyengine_api_pr.yml").read_text())
        self.assertEqual(problems, [])
        self.assertIn("make test", jobs["test"].run_text)
        self.assertIn("ruff format --check", jobs["lint"].run_text)
        self.assertIn("run_quality_guards.py", jobs["quality-guards"].run_text)
        self.assertIn("unittest discover", jobs["quality-guards"].run_text)
        self.assertTrue(jobs["alembic-v1-check"].invokes("alembic-v1-check.yml"))
        self.assertEqual(jobs["typecheck-v2"].name, "Type-check API v2")

    def test_policyengine_sim_api_pr_workflow(self) -> None:
        jobs, problems = parse_jobs(
            (FIXTURES / "policyengine_sim_api_pr.yml").read_text()
        )
        self.assertEqual(problems, [])
        self.assertIn(
            "projects/policyengine-simulation-entry", jobs["test"].matrix["project"]
        )
        self.assertIn(
            "libs/policyengine-stage12-persistence", jobs["test"].matrix["project"]
        )
        self.assertIn("uv run pytest tests/", jobs["test"].run_text)
        self.assertIn("ruff format --check", jobs["lint"].run_text)
        self.assertIn("run_quality_guards.py", jobs["quality-guards"].run_text)
        self.assertTrue(jobs["docker-build"].invokes("docker/build-push-action"))


class SubsetTest(unittest.TestCase):
    def test_block_scalar_stops_at_sibling_key(self) -> None:
        text = """
jobs:
  build:
    steps:
      - name: Build
        run: |
          make build
        env:
          FLAG: make test
"""
        jobs, _ = parse_jobs(text)
        self.assertFalse(jobs["build"].invokes("make test"))
        self.assertTrue(jobs["build"].invokes("make build"))

    def test_comments_are_ignored(self) -> None:
        text = (
            "jobs:\n  a:\n    steps:\n      # run: make test\n"
            "      - run: echo hi # make test\n"
        )
        jobs, _ = parse_jobs(text)
        self.assertFalse(jobs["a"].invokes("make test"))

    def test_quoted_hash_is_not_a_comment(self) -> None:
        jobs, _ = parse_jobs(
            'jobs:\n  a:\n    steps:\n      - run: "echo #1 && make test"\n'
        )
        self.assertTrue(jobs["a"].invokes("make test"))

    def test_inline_matrix_list(self) -> None:
        jobs, _ = parse_jobs(
            "jobs:\n  a:\n    strategy:\n      matrix:\n"
            '        python: ["3.12", "3.13"]\n'
        )
        self.assertEqual(jobs["a"].matrix["python"], ("3.12", "3.13"))

    def test_anchors_are_reported(self) -> None:
        _, problems = parse_jobs("jobs:\n  a: &base\n    steps: []\n")
        self.assertTrue(problems)


SYNTHETIC_WORKFLOW = """
name: Synthetic
on: push
jobs:
  test:
    name: "Quoted name"
    strategy:
      matrix:
        project: [a, "b", 'c']
        python:
          - "3.11"
          - 3.12

          - '3.13'
        include:
          - project: x
    steps:
      - name: First
        run: >
          folded one
          folded two
      -   uses: actions/checkout@v4
      - run: echo a && echo b
      - "just a string"
      - name: Third
        run: |
          echo "a; b"

          echo ${{ x || y }}
      - name: Fourth
        uses: org/action@v1
        with:
          - name: not a step
  reusable:
    uses: org/repo/.github/workflows/x.yml@main
  other:
    steps:
    - name: Unindented list
      run: make test
    - run: |
        multi
        line
      name: Named after run
permissions: {}
"""


class JobParsingTest(unittest.TestCase):
    """Pins every field the reader extracts from a job, quirks included."""

    def setUp(self) -> None:
        self.jobs, self.problems = parse_jobs(SYNTHETIC_WORKFLOW)

    def test_jobs_end_at_the_next_top_level_key(self) -> None:
        self.assertEqual(self.problems, [])
        self.assertEqual(list(self.jobs), ["test", "reusable", "other"])

    def test_job_with_matrix_and_steps(self) -> None:
        self.assertEqual(
            self.jobs["test"],
            JobBlock(
                id="test",
                name="Quoted name",
                run_text=(
                    'folded one\nfolded two\necho a && echo b\necho "a; b"\n\n'
                    "echo ${{ x || y }}"
                ),
                uses="",
                step_names=("First", "Third", "Fourth", "not a step"),
                step_uses=("actions/checkout@v4", "org/action@v1"),
                # A blank line ends a block-style matrix list.
                matrix={
                    "project": ("a", "b", "c"),
                    "python": ("3.11", "3.12"),
                    "include": (),
                },
                run_blocks=(
                    RunBlock(
                        step="First",
                        code_lines=2,
                        chained=False,
                        text="folded one\nfolded two",
                    ),
                    RunBlock(
                        step="step 3",
                        code_lines=1,
                        chained=True,
                        text="echo a && echo b",
                    ),
                    RunBlock(
                        step="Third",
                        code_lines=2,
                        chained=False,
                        text='echo "a; b"\n\necho ${{ x || y }}',
                    ),
                ),
            ),
        )

    def test_reusable_workflow_job(self) -> None:
        self.assertEqual(
            self.jobs["reusable"],
            JobBlock(
                id="reusable",
                name="reusable",
                run_text="",
                uses="org/repo/.github/workflows/x.yml@main",
                step_names=(),
            ),
        )

    def test_steps_listed_at_the_key_indent(self) -> None:
        self.assertEqual(
            self.jobs["other"],
            JobBlock(
                id="other",
                name="other",
                run_text="make test\nmulti\nline",
                uses="",
                step_names=("Unindented list", "Named after run"),
                run_blocks=(
                    RunBlock(
                        step="Unindented list",
                        code_lines=1,
                        chained=False,
                        text="make test",
                    ),
                    RunBlock(
                        step="Named after run",
                        code_lines=2,
                        chained=False,
                        text="multi\nline",
                    ),
                ),
            ),
        )

    def test_flow_style_jobs_are_reported(self) -> None:
        self.assertEqual(
            parse_jobs("jobs: {a: 1}\n"),
            ({}, ["flow-style 'jobs:' mapping is not supported"]),
        )

    def test_workflow_without_jobs(self) -> None:
        self.assertEqual(parse_jobs("name: x\n"), ({}, []))

    def test_stray_job_level_line_is_reported(self) -> None:
        jobs, problems = parse_jobs(
            "jobs:\n  a:\n    steps: []\n  - stray\n  b:\n    name: B\n"
        )
        self.assertEqual(list(jobs), ["a", "b"])
        self.assertEqual(jobs["b"].name, "B")
        self.assertEqual(problems, ["unexpected line at job level: '- stray'"])


if __name__ == "__main__":
    unittest.main()
