"""Tests that a ratcheted rule's baseline gains no entry the base branch lacks."""

from __future__ import annotations

import os
import subprocess
import unittest
from unittest import mock

from scripts.rules.baseline import default_base_ref
from scripts.rules.tests.support import Repo
from scripts.rules.tests.test_guard import RATCHETED_RULE, with_rule

GIT = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]
BASELINE = "rules/baselines/ratcheted.txt"


def _commit_base(repo: Repo) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo.root, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=repo.root, check=True)
    subprocess.run([*GIT, "commit", "-qm", "base"], cwd=repo.root, check=True)


class TestBaselineEntries(unittest.TestCase):
    """A baseline may lose entries, but never swap one for a new one."""

    def test_a_swapped_entry_fails_although_the_count_is_unchanged(self) -> None:
        with Repo(with_rule(RATCHETED_RULE.format(count=2)), render=False) as repo:
            repo.write(BASELINE, "pkg/routes.py\npkg/models.py\n")
            repo.render()
            _commit_base(repo)
            repo.write(BASELINE, "pkg/routes.py\npkg/other.py\n")
            messages = repo.messages(base_ref="HEAD")
        self.assertIn(
            "[ex.layers.ratcheted] baseline: rules/baselines/ratcheted.txt lists "
            "entries the base branch's copy doesn't: pkg/other.py. Fix: fix the "
            "new violations instead of adding them to the baseline.",
            messages,
        )

    def test_an_added_copy_of_a_listed_entry_fails_at_the_same_count(self) -> None:
        with Repo(with_rule(RATCHETED_RULE.format(count=3)), render=False) as repo:
            repo.write(BASELINE, "pkg/routes.py\npkg/routes.py\npkg/models.py\n")
            repo.render()
            _commit_base(repo)
            repo.write(BASELINE, "pkg/routes.py\npkg/routes.py\npkg/routes.py\n")
            messages = repo.messages(base_ref="HEAD")
        self.assertIn(
            "[ex.layers.ratcheted] baseline: rules/baselines/ratcheted.txt lists "
            "entries the base branch's copy doesn't: pkg/routes.py (3 times, the "
            "base branch 2). Fix: fix the new violations instead of adding them to "
            "the baseline.",
            messages,
        )

    def test_a_removed_entry_passes(self) -> None:
        with Repo(with_rule(RATCHETED_RULE.format(count=2)), render=False) as repo:
            repo.write(BASELINE, "pkg/routes.py\npkg/models.py\n")
            repo.render()
            _commit_base(repo)
            repo.edit("rules/registry.toml", "count = 2", "count = 1")
            repo.write(BASELINE, "# Tolerated.\npkg/routes.py\n")
            repo.render()
            self.assertEqual(repo.messages(base_ref="HEAD"), [])


class TestDefaultBaseRef(unittest.TestCase):
    """The ref baselines and rule statuses are compared with, by default."""

    def test_rules_base_ref_is_used_as_given(self) -> None:
        # make quality-check passes the merge base, a commit, this way.
        environment = {"RULES_BASE_REF": "4f2960b6", "GITHUB_BASE_REF": "master"}
        with mock.patch.dict(os.environ, environment):
            self.assertEqual(default_base_ref(), "4f2960b6")

    def test_the_pull_request_s_base_branch_otherwise(self) -> None:
        environment = {"RULES_BASE_REF": "", "GITHUB_BASE_REF": "master"}
        with mock.patch.dict(os.environ, environment):
            self.assertEqual(default_base_ref(), "origin/master")

    def test_none_without_either(self) -> None:
        with mock.patch.dict(os.environ, {"RULES_BASE_REF": "", "GITHUB_BASE_REF": ""}):
            self.assertIsNone(default_base_ref())


if __name__ == "__main__":
    unittest.main()
