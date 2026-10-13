"""Tests for the GitHub Actions subset reader.

They are pinned against both repos' real PR workflows.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.rules.workflows import parse_jobs

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


if __name__ == "__main__":
    unittest.main()
