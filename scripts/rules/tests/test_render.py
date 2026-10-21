"""Tests for the rendered views: enforcer descriptions and the mermaid graphs."""

from __future__ import annotations

import unittest

from scripts.rules.model import (
    Category,
    CiRef,
    Discovery,
    Enforcer,
    Kind,
    Registry,
    Rule,
    Status,
    Tier,
)
from scripts.rules.render import render_rules_md

PR_WORKFLOW = ".github/workflows/pr.yml"


def make_rule(
    rule_id: str,
    enforcer: Enforcer,
    ci: tuple[CiRef, ...] = (),
    status: Status = Status.ENFORCED,
) -> Rule:
    return Rule(
        id=rule_id,
        category="checks",
        statement="A statement.",
        rationale="docs/guide.md",
        scope=("pkg/*.py",),
        tier=Tier.MECHANICAL,
        status=status,
        autofix=False,
        enforcer=enforcer,
        ci=ci,
    )


def mermaid_blocks(rules: tuple[Rule, ...]) -> list[list[str]]:
    """Render the rules in one category and return each mermaid block's lines."""
    registry = Registry(
        schema_version=1,
        repo="example",
        categories=(Category("checks", "Checks"),),
        discovery=Discovery(),
        rules=rules,
    )
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in render_rules_md(registry).splitlines():
        if line == "```mermaid":
            current = [line]
        elif current is not None:
            current.append(line)
            if line == "```":
                blocks.append(current)
                current = None
    return blocks


def rule_node(number: int) -> str:
    """Return the mermaid declaration of the numbered rule in the chunking test."""
    return f'  r_ex_many_rule_{number:02d}("ex.many.rule-{number:02d} (enforced)")'


class EnforcerDescriptionTest(unittest.TestCase):
    def test_each_kind_describes_its_checker(self) -> None:
        cases: list[tuple[Kind, dict[str, object], str]] = [
            (
                Kind.PYTEST,
                {"project": "proj/", "nodes": ["b.py::t", "a.py::u", "a.py::v"]},
                "pytest `proj/a.py`, `proj/b.py`",
            ),
            (Kind.PYTEST, {"nodes": ["x.py"]}, "pytest `x.py`"),
            (Kind.PYTEST, {}, "pytest "),
            (
                Kind.QUALITY_GUARD,
                {"name": "rules-registry"},
                "quality guard `rules-registry`",
            ),
            (Kind.QUALITY_GUARD, {}, "quality guard ``"),
            (Kind.RUFF, {"codes": ["E1"], "mode": "format"}, "ruff format"),
            (
                Kind.RUFF,
                {"codes": ["E1", "F2"], "mode": "per-file-ignore", "pattern": "t/**"},
                "ruff per-file ignore of E1, F2 for `t/**`",
            ),
            (Kind.RUFF, {"mode": "per-file-ignore"}, "ruff per-file ignore of  for ``"),
            (Kind.RUFF, {"codes": ["E1", "F2"], "mode": "lint"}, "ruff check (E1, F2)"),
            (Kind.RUFF, {}, "ruff check ()"),
            (Kind.MYPY, {"paths": ["pkg"]}, "mypy"),
            (Kind.WORKFLOW_JOB, {"step": "Build"}, "CI job"),
            (
                Kind.PYRIGHT,
                {"config": "pyrightconfig.json"},
                "pyright `pyrightconfig.json`",
            ),
            (Kind.PYRIGHT, {}, "pyright ``"),
            (
                Kind.IMPORT_LINTER,
                {"config": ".importlinter"},
                "import-linter `.importlinter`",
            ),
            (Kind.DOCS_GUARD, {"doc": "docs/x.md"}, "docs guard on `docs/x.md`"),
            (Kind.DOCS_GUARD, {}, "docs guard on ``"),
            (Kind.LLM_REVIEW, {"prompt": "p.md"}, "LLM review with `p.md`"),
            (Kind.LLM_REVIEW, {}, "LLM review with ``"),
            (Kind.NONE, {"name": "ignored"}, "nothing"),
        ]
        for kind, fields, expected in cases:
            with self.subTest(kind=kind, fields=fields):
                self.assertEqual(Enforcer(kind, fields).description, expected)


class MermaidTest(unittest.TestCase):
    def test_graph_declares_each_node_once_and_skips_repeated_edges(self) -> None:
        guard = Enforcer(Kind.QUALITY_GUARD, {"name": 'say "hi"'})
        mypy = Enforcer(Kind.MYPY, {"paths": ["pkg"]})
        rules = (
            make_rule("ex.a.unenforced", Enforcer(Kind.NONE), status=Status.DOC_ONLY),
            make_rule(
                "ex.b.also-unenforced", Enforcer(Kind.NONE), status=Status.DOC_ONLY
            ),
            make_rule(
                "ex.c.guard",
                guard,
                (
                    CiRef(PR_WORKFLOW, "guards", "run"),
                    CiRef(".github/workflows/push.yml", "guards", "run"),
                ),
            ),
            make_rule("ex.d.same-guard", guard, (CiRef(PR_WORKFLOW, "guards", "run"),)),
            make_rule("ex.e.local", mypy),
            make_rule("ex.f.local-too", mypy),
            make_rule(
                "ex.g.job",
                Enforcer(Kind.WORKFLOW_JOB),
                (
                    CiRef(PR_WORKFLOW, "build", "make"),
                    CiRef(PR_WORKFLOW, "deploy", "make"),
                ),
            ),
        )
        self.assertEqual(
            mermaid_blocks(rules),
            [
                [
                    "```mermaid",
                    "flowchart LR",
                    '  r_ex_a_unenforced("ex.a.unenforced (doc-only)")',
                    '  gap_unenforced>"not enforced"]',
                    '  r_ex_b_also_unenforced("ex.b.also-unenforced (doc-only)")',
                    '  r_ex_c_guard("ex.c.guard (enforced)")',
                    "  e_quality_guard_say__hi_[\"quality guard say 'hi'\"]",
                    '  j_CI_pr_yml_guards["CI pr.yml:guards"]',
                    '  j_CI_push_yml_guards["CI push.yml:guards"]',
                    '  r_ex_d_same_guard("ex.d.same-guard (enforced)")',
                    '  r_ex_e_local("ex.e.local (enforced)")',
                    '  e_mypy["mypy"]',
                    '  local_only>"not run in CI"]',
                    '  r_ex_f_local_too("ex.f.local-too (enforced)")',
                    '  r_ex_g_job("ex.g.job (enforced)")',
                    '  e_CI_job_build__deploy["CI job build, deploy"]',
                    '  j_CI_pr_yml_build["CI pr.yml:build"]',
                    '  j_CI_pr_yml_deploy["CI pr.yml:deploy"]',
                    "  r_ex_a_unenforced -.-> gap_unenforced",
                    "  r_ex_b_also_unenforced -.-> gap_unenforced",
                    "  r_ex_c_guard --> e_quality_guard_say__hi_",
                    "  e_quality_guard_say__hi_ --> j_CI_pr_yml_guards",
                    "  e_quality_guard_say__hi_ --> j_CI_push_yml_guards",
                    "  r_ex_d_same_guard --> e_quality_guard_say__hi_",
                    "  r_ex_e_local --> e_mypy",
                    "  e_mypy -.-> local_only",
                    "  r_ex_f_local_too --> e_mypy",
                    "  r_ex_g_job --> e_CI_job_build__deploy",
                    "  e_CI_job_build__deploy --> j_CI_pr_yml_build",
                    "  e_CI_job_build__deploy --> j_CI_pr_yml_deploy",
                    "```",
                ]
            ],
        )

    def test_large_graphs_are_split_into_chunks_of_rules(self) -> None:
        rules = tuple(
            make_rule(
                f"ex.many.rule-{number:02d}",
                Enforcer(Kind.QUALITY_GUARD, {"name": f"guard-{number:02d}"}),
                (CiRef(PR_WORKFLOW, f"job-{number:02d}", "run"),),
            )
            for number in range(20)
        )
        blocks = mermaid_blocks(rules)
        self.assertEqual([len(block) for block in blocks], [78, 28])
        self.assertEqual(
            [
                [line for line in block if line.startswith("  r_") and "(" in line]
                for block in blocks
            ],
            [
                [rule_node(number) for number in range(15)],
                [rule_node(number) for number in range(15, 20)],
            ],
        )


if __name__ == "__main__":
    unittest.main()
