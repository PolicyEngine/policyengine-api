"""Tests for loading rule tables: every schema problem is reported, in order."""

from __future__ import annotations

import tomllib
import unittest
from datetime import date

from scripts.rules.load import parse
from scripts.rules.model import (
    Baseline,
    CiRef,
    Enforcer,
    Kind,
    Proof,
    Rule,
    RuleException,
    Status,
    Tier,
)
from scripts.rules.tests.support import REGISTRY

BOUNDARY_NODE = "tests/unit/test_boundaries.py::test_routes_have_no_sql"
KNOWN_RULE_KEYS = (
    "['autofix', 'baseline', 'category', 'ci', 'downgrade', 'enforcer', "
    "'exception', 'id', 'proof', 'rationale', 'review_by', 'scope', 'statement', "
    "'status', 'tier']"
)
KINDS = (
    "['pytest', 'quality-guard', 'ruff', 'mypy', 'pyright', 'import-linter', "
    "'workflow-job', 'docs-guard', 'llm-review', 'none']"
)
MALFORMED = "[ex.layers.malformed] schema: ex.layers.malformed"

MALFORMED_RULE = {
    "id": "ex.layers.malformed",
    "category": "layers",
    "statement": "Malformed.",
    "rationale": "docs/guide.md",
    "scope": ["pkg/*.py"],
    "tier": "mechanical",
    "status": "enforced",
    "autofix": "yes",
    "review_by": "someday",
    "enforcer": "pytest",
    "ci": [
        5,
        {
            "workflow": ".github/workflows/pr.yml",
            "job": "",
            "invocation": "make test",
            "extra": 1,
        },
    ],
    "proof": "proof.py",
    "baseline": {"file": "rules/baselines/x.txt"},
    "exception": [
        7,
        {"path": "pkg/*.py", "reason": "r", "expires": "soon", "extra": 1},
    ],
    "downgrade": {"why": "x"},
    "bogus": 1,
}
UNKNOWN_TIER_RULE = {
    "category": "layers",
    "tier": "unknown",
    "status": "enforced",
    "autofix": False,
    "enforcer": {"kind": "flake8", "codes": ["E1"]},
}
SINGLE_TABLES_RULE = {
    "id": "ex.layers.single-tables",
    "category": "layers",
    "statement": "Single tables.",
    "rationale": "docs/guide.md",
    "scope": ["pkg/*.py"],
    "tier": "metric",
    "status": "ratcheted",
    "autofix": True,
    "review_by": date(2026, 7, 1),
    "enforcer": {"kind": "pytest", "nodes": [BOUNDARY_NODE]},
    "ci": {
        "workflow": ".github/workflows/pr.yml",
        "job": "test",
        "invocation": "make test",
    },
    "proof": {"test": BOUNDARY_NODE},
    "baseline": {"file": "rules/baselines/x.txt", "count": 2, "extra": True},
    "exception": {"path": "pkg/*.py", "reason": "legacy", "expires": "2026-12-31"},
    "downgrade": {"reason": "too noisy"},
}


class RuleTableTest(unittest.TestCase):
    def setUp(self) -> None:
        raw = tomllib.loads(REGISTRY)
        raw["rule"] = [
            "not a table",
            MALFORMED_RULE,
            UNKNOWN_TIER_RULE,
            SINGLE_TABLES_RULE,
        ]
        self.registry, self.violations = parse(raw)

    def test_every_problem_is_reported_in_order(self) -> None:
        self.assertEqual(
            [str(violation) for violation in self.violations],
            [
                "[registry] schema: rule #1 must be a table. Fix: write [[rule]].",
                "[ex.layers.malformed] schema: unknown key 'bogus' in "
                "ex.layers.malformed. Fix: remove it or use one of "
                f"{KNOWN_RULE_KEYS}.",
                f"{MALFORMED}.enforcer must be a table. Fix: add [rule.enforcer].",
                f"{MALFORMED}.ci entries must be tables. Fix: write [[rule.ci]].",
                "[ex.layers.malformed] schema: unknown key 'extra' in "
                "ex.layers.malformed.ci. Fix: remove it or use one of "
                "['invocation', 'job', 'workflow'].",
                f"{MALFORMED}.ci.job must be a non-empty string. Fix: set job.",
                f"{MALFORMED}.proof must be a table. Fix: write [rule.proof].",
                f"{MALFORMED}.baseline needs 'file' and an integer 'count'. "
                "Fix: write [rule.baseline] with file and count.",
                f"{MALFORMED}.exception entries must be tables. "
                "Fix: write [[rule.exception]].",
                "[ex.layers.malformed] schema: unknown key 'extra' in "
                "ex.layers.malformed.exception. Fix: remove it or use one of "
                "['expires', 'path', 'reason'].",
                f"{MALFORMED}.exception.expires must be a date. "
                "Fix: write it as YYYY-MM-DD.",
                f"{MALFORMED}.downgrade needs a 'reason'. "
                'Fix: write [rule.downgrade] reason = "...".',
                f"{MALFORMED}.autofix must be true or false. Fix: set autofix.",
                f"{MALFORMED}.review_by must be a date. Fix: write it as YYYY-MM-DD.",
                f"[registry] schema: rule #3.enforcer.kind is 'flake8'. "
                f"Fix: use one of {KINDS}.",
                "[registry] schema: rule #3.tier is 'unknown'. "
                "Fix: use one of ['mechanical', 'metric', 'judgment'].",
                "[ex.layers.single-tables] schema: unknown key 'extra' in "
                "ex.layers.single-tables.baseline. Fix: remove it or use one of "
                "['count', 'file'].",
            ],
        )

    def test_malformed_fields_fall_back_to_safe_values(self) -> None:
        assert self.registry is not None
        self.assertEqual(
            self.registry.rule("ex.layers.malformed"),
            Rule(
                id="ex.layers.malformed",
                category="layers",
                statement="Malformed.",
                rationale="docs/guide.md",
                scope=("pkg/*.py",),
                tier=Tier.MECHANICAL,
                status=Status.ENFORCED,
                autofix=False,
                enforcer=Enforcer(Kind.NONE),
                ci=(CiRef(".github/workflows/pr.yml", "", "make test"),),
                exceptions=(RuleException("pkg/*.py", "r", date.max),),
            ),
        )

    def test_a_rule_with_an_unknown_tier_is_dropped(self) -> None:
        assert self.registry is not None
        self.assertEqual(
            [rule.id for rule in self.registry.rules],
            ["ex.layers.malformed", "ex.layers.single-tables"],
        )

    def test_single_tables_stand_for_one_entry_lists(self) -> None:
        assert self.registry is not None
        self.assertEqual(
            self.registry.rule("ex.layers.single-tables"),
            Rule(
                id="ex.layers.single-tables",
                category="layers",
                statement="Single tables.",
                rationale="docs/guide.md",
                scope=("pkg/*.py",),
                tier=Tier.METRIC,
                status=Status.RATCHETED,
                autofix=True,
                enforcer=Enforcer(Kind.PYTEST, {"nodes": [BOUNDARY_NODE]}),
                ci=(CiRef(".github/workflows/pr.yml", "test", "make test"),),
                review_by=date(2026, 7, 1),
                proof=Proof({"test": BOUNDARY_NODE}),
                baseline=Baseline("rules/baselines/x.txt", 2),
                exceptions=(RuleException("pkg/*.py", "legacy", date(2026, 12, 31)),),
                downgrade_reason="too noisy",
            ),
        )


if __name__ == "__main__":
    unittest.main()
