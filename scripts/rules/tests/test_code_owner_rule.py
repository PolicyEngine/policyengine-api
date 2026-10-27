"""Tests that the code-owner rule says what GitHub enforces when merging.

The default branch's ruleset needs one approving review from anyone with write
access and doesn't require code-owner review, so a core developer's approval of
rule changes is a team convention, and the rule's statement has to say so.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.rules.load import load_registry
from scripts.rules.model import Rule, Status

REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_OWNER_RULE_ID = "api.process.rule-machinery-code-owned"
REQUIRED_APPROVAL = (
    "Changes to the rule machinery (rules/, scripts/rules/, scripts/guards/, "
    "scripts/run_quality_guards.py and CODEOWNERS) need approval from a core "
    "developer other than the author."
)


class CodeOwnerRuleTest(unittest.TestCase):
    """The rule keeps its requirement and says GitHub doesn't enforce it."""

    def code_owner_rule(self) -> Rule:
        """Return the code-owner rule from the repository's own registry."""
        registry, violations = load_registry(REPO_ROOT)
        if registry is None:
            self.fail(f"rules/registry.toml doesn't load: {violations}")
        rule = registry.rule(CODE_OWNER_RULE_ID)
        if rule is None:
            self.fail(f"{CODE_OWNER_RULE_ID} isn't in rules/registry.toml")
        return rule

    def test_rule_still_asks_for_a_core_developer_approval(self) -> None:
        """The statement still starts with the approval the rule asks for."""
        statement = self.code_owner_rule().statement
        self.assertTrue(statement.startswith(REQUIRED_APPROVAL), statement)

    def test_rule_stays_doc_only(self) -> None:
        """No check enforces the rule, so it stays doc-only."""
        self.assertIs(self.code_owner_rule().status, Status.DOC_ONLY)

    def test_rule_says_github_does_not_require_code_owner_review(self) -> None:
        """The statement says what the ruleset needs, and that it's a convention."""
        statement = self.code_owner_rule().statement
        self.assertIn("team convention that GitHub doesn't enforce", statement)
        self.assertIn("one approving review from anyone with write access", statement)
        self.assertIn("doesn't require code-owner review", statement)


if __name__ == "__main__":
    unittest.main()
