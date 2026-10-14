"""Tests for registry validation: every problem is reported, in a stable order."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.rules.load import load_text
from scripts.rules.tests.support import REGISTRY, TODAY, Repo
from scripts.rules.validate import validate

FIXTURES = Path(__file__).parent / "fixtures" / "validate"


class BrokenRegistryTest(unittest.TestCase):
    """One registry that breaks every validation check at least once."""

    def test_every_violation_is_reported_in_order(self) -> None:
        files = {
            "rules/registry.toml": REGISTRY
            + "\n"
            + (FIXTURES / "broken_rules.toml").read_text(),
            "CLAUDE.md": "Read AGENTS.md.\n",
            "rules/baselines/ci-multiline-run.txt": "",
            "rules/baselines/ruff.txt": (
                "# header\n\nentry one\n  # indented comment\nentry two\n"
            ),
        }
        with Repo(files, render=False) as repo:
            registry, load_violations = load_text(repo.read("rules/registry.toml"))
            self.assertEqual(load_violations, [])
            assert registry is not None
            self.assertEqual(
                [str(violation) for violation in validate(registry, repo.root, TODAY)],
                (FIXTURES / "broken_rules_violations.txt").read_text().splitlines(),
            )


if __name__ == "__main__":
    unittest.main()
