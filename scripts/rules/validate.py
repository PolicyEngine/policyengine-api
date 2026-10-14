"""Semantic validation of a parsed registry against the repository tree."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any

from scripts.rules.model import Kind, Registry, Rule, Status, Tier, Violation
from scripts.rules.resolve import node_exists

if TYPE_CHECKING:
    from pathlib import Path

RULE_ID = re.compile(r"^[a-z0-9]+(\.[a-z0-9][a-z0-9-]*)+$")

# Required and optional enforcer fields per kind, with their expected types.
KIND_FIELDS: dict[Kind, tuple[dict[str, type], dict[str, type]]] = {
    Kind.PYTEST: ({"nodes": list}, {"project": str}),
    Kind.QUALITY_GUARD: ({"name": str}, {"runner": str}),
    Kind.RUFF: ({"mode": str}, {"codes": list, "pattern": str, "config": str}),
    Kind.MYPY: ({"paths": list}, {"config": str}),
    Kind.PYRIGHT: ({"config": str}, {"project": str}),
    Kind.IMPORT_LINTER: ({"config": str, "contract": str}, {}),
    Kind.WORKFLOW_JOB: ({}, {"step": str}),
    Kind.DOCS_GUARD: ({"doc": str, "marker": str}, {}),
    Kind.LLM_REVIEW: ({"prompt": str, "model": str}, {}),
    Kind.NONE: ({}, {}),
}

RUFF_MODES = ("format", "lint", "per-file-ignore")

PROOF_FIELDS: dict[Tier, dict[str, Any]] = {
    Tier.MECHANICAL: {"bad_fixture": str, "good_fixture": str, "test": str},
    Tier.METRIC: {
        "below_fixture": str,
        "above_fixture": str,
        "threshold": (int, float),
        "test": str,
    },
    Tier.JUDGMENT: {
        "eval_set": str,
        "min_precision": float,
        "measured_precision": float,
        "measured_on": date,
    },
}
PROOF_FILE_FIELDS = (
    "bad_fixture",
    "good_fixture",
    "below_fixture",
    "above_fixture",
    "eval_set",
)


def baseline_entries(path: Path) -> int:
    """Count the entries in a baseline file, skipping blank and ``#`` comment lines."""
    return sum(
        1
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _check_fields(
    rule: Rule,
    fields: dict[str, Any],
    required: dict[str, Any],
    optional: dict[str, Any],
    where: str,
) -> list[Violation]:
    violations = []
    for key, expected in required.items():
        if key not in fields:
            violations.append(
                Violation(
                    rule.id, "schema", f"{where} is missing '{key}'", f"add {key}"
                )
            )
        elif not isinstance(fields[key], expected):
            violations.append(
                Violation(
                    rule.id,
                    "schema",
                    f"{where}.{key} has the wrong type",
                    f"make it a {expected}",
                )
            )
    violations.extend(
        Violation(
            rule.id,
            "schema",
            f"unknown key '{key}' in {where}",
            f"remove it; allowed: {sorted({**required, **optional})}",
        )
        for key in sorted(set(fields) - set(required) - set(optional))
    )
    return violations


def _validate_enforcer(rule: Rule) -> list[Violation]:
    required, optional = KIND_FIELDS[rule.enforcer.kind]
    where = f"enforcer ({rule.enforcer.kind})"
    violations = _check_fields(
        rule, dict(rule.enforcer.fields), required, optional, where
    )
    kind, fields = rule.enforcer.kind, rule.enforcer.fields
    if kind is Kind.PYTEST and not fields.get("nodes"):
        violations.append(
            Violation(
                rule.id,
                "schema",
                "pytest enforcer has no nodes",
                "list at least one test node",
            )
        )
    if kind is Kind.RUFF:
        mode = fields.get("mode")
        if mode not in RUFF_MODES:
            violations.append(
                Violation(
                    rule.id,
                    "schema",
                    f"ruff mode is {mode!r}",
                    f"use one of {list(RUFF_MODES)}",
                )
            )
        if mode in ("lint", "per-file-ignore") and not fields.get("codes"):
            violations.append(
                Violation(
                    rule.id, "schema", f"ruff {mode} needs codes", "list the ruff codes"
                )
            )
        if mode == "per-file-ignore" and not fields.get("pattern"):
            violations.append(
                Violation(
                    rule.id,
                    "schema",
                    "ruff per-file-ignore needs a pattern",
                    "set pattern",
                )
            )
    return violations


def _validate_cross_fields(rule: Rule) -> list[Violation]:
    violations = []

    def v(message: str, fix: str) -> None:
        violations.append(Violation(rule.id, "schema", message, fix))

    kind, status, tier = rule.enforcer.kind, rule.status, rule.tier
    if status is Status.DOC_ONLY and kind is not Kind.NONE:
        v(
            "doc-only rules have no enforcer",
            'set enforcer.kind = "none", or pick a stronger status',
        )
    if status is Status.DOC_ONLY and rule.ci:
        v(
            "doc-only rules have no CI wiring",
            "remove rule.ci, or pick a stronger status",
        )
    if kind is Kind.NONE and status not in (Status.DOC_ONLY, Status.ADVISORY):
        v(
            f"status {status} needs an enforcer",
            "add [rule.enforcer] or use doc-only/advisory",
        )
    if status in (Status.ENFORCED, Status.RATCHETED) and not rule.ci:
        v(f"{status} rules must run in CI", "add a [[rule.ci]] reference")
    if status is Status.RATCHETED and rule.baseline is None:
        v("ratcheted rules need a baseline", "add [rule.baseline] or use enforced")
    if rule.baseline is not None and status is not Status.RATCHETED:
        v(
            "only ratcheted rules may have a baseline",
            'remove [rule.baseline] or set status = "ratcheted"',
        )
    if kind is Kind.RUFF and rule.baseline is not None:
        v(
            "ruff is never ratcheted",
            "remove the baseline and fix every violation in a standalone PR that "
            "also changes the ruff select list",
        )
    if tier is Tier.JUDGMENT and kind not in (Kind.LLM_REVIEW, Kind.NONE):
        v(
            "judgment rules are enforced by review, not by a mechanical checker",
            'use enforcer.kind = "llm-review" or "none"',
        )
    if kind is Kind.LLM_REVIEW and tier is not Tier.JUDGMENT:
        v("llm-review only enforces judgment rules", 'set tier = "judgment"')
    return violations


def _validate_proof(rule: Rule, root: Path) -> list[Violation]:
    if rule.proof is None:
        return []
    fields = dict(rule.proof.fields)
    optional = (
        {"project": str, "workflow": str, "job": str, "invocation": str}
        if "test" in PROOF_FIELDS[rule.tier]
        else {}
    )
    violations = _check_fields(
        rule, fields, PROOF_FIELDS[rule.tier], optional, f"proof ({rule.tier})"
    )
    named = [key for key in ("workflow", "job", "invocation") if key in fields]
    if named and len(named) != 3:
        violations.append(
            Violation(
                rule.id,
                "schema",
                "proof names its CI job only partly",
                "set all of proof.workflow, proof.job and proof.invocation, or none",
            )
        )
    for key in PROOF_FILE_FIELDS:
        if isinstance(fields.get(key), str) and not (root / fields[key]).exists():
            violations.append(
                Violation(
                    rule.id,
                    "proof",
                    f"proof {key} {fields[key]} does not exist",
                    "add the fixture or fix the path",
                )
            )
    test = fields.get("test")
    if isinstance(test, str):
        prefix = (
            f"{fields['project'].rstrip('/')}/"
            if isinstance(fields.get("project"), str)
            else ""
        )
        problem = node_exists(root, prefix + test)
        if problem:
            violations.append(
                Violation(
                    rule.id,
                    "proof",
                    problem,
                    "point proof.test at the test that runs the fixtures",
                )
            )
    return violations


def validate(registry: Registry, root: Path, today: date) -> list[Violation]:
    """Check the registry's fields and file references against the tree at ``root``.

    ``today`` decides whether review dates and exceptions have expired.
    """
    violations: list[Violation] = []

    def v(rule_id: str | None, message: str, fix: str, check: str = "schema") -> None:
        violations.append(Violation(rule_id, check, message, fix))

    if registry.agents is not None:
        for path in (registry.agents.instructions, *registry.agents.adapters):
            if path and not (root / path).is_file():
                v(
                    None,
                    f"agents file {path} does not exist",
                    "fix [agents] or create the file",
                )
    if registry.ci_scripts is not None:
        config = registry.ci_scripts
        if config.scripts_dir and not (root / config.scripts_dir).is_dir():
            v(
                None,
                f"ci_scripts.scripts_dir {config.scripts_dir} does not exist",
                "fix [ci_scripts]",
            )
        for path in (
            config.multiline_baseline,
            config.untested_baseline,
            config.shellcheck_baseline,
        ):
            if path and not (root / path).is_file():
                v(
                    None,
                    f"ci_scripts baseline {path} does not exist",
                    "create it (it may be empty)",
                )

    category_ids = [category.id for category in registry.categories]
    for duplicate in sorted({c for c in category_ids if category_ids.count(c) > 1}):
        v(None, f"duplicate category '{duplicate}'", "give each category a unique id")

    rule_ids = [rule.id for rule in registry.rules]
    for duplicate in sorted({r for r in rule_ids if rule_ids.count(r) > 1}):
        v(duplicate, "duplicate rule id", "give each rule a unique id")

    for rule in registry.rules:
        if rule.id and not RULE_ID.match(rule.id):
            v(
                rule.id,
                "id must be lowercase dotted, e.g. 'api.v2.routes-no-sql'",
                "rename the rule",
            )
        if rule.category not in category_ids:
            v(
                rule.id,
                f"unknown category '{rule.category}'",
                f"use one of {category_ids} or add a [[category]]",
            )

        rationale_path = rule.rationale.split("#", 1)[0]
        if rationale_path and not (root / rationale_path).exists():
            v(
                rule.id,
                f"rationale {rationale_path} does not exist",
                "link an existing doc",
            )

        for pattern in rule.scope:
            if not any(root.glob(pattern)):
                v(rule.id, f"scope '{pattern}' matches no files", "fix the glob")

        violations.extend(_validate_enforcer(rule))
        violations.extend(_validate_cross_fields(rule))
        violations.extend(_validate_proof(rule, root))

        if rule.baseline is not None:
            path = root / rule.baseline.file
            if not path.is_file():
                v(
                    rule.id,
                    f"baseline file {rule.baseline.file} does not exist",
                    "create it",
                    "baseline",
                )
            elif baseline_entries(path) != rule.baseline.count:
                v(
                    rule.id,
                    f"baseline count is {rule.baseline.count} but "
                    f"{rule.baseline.file} lists {baseline_entries(path)}",
                    "make the count match the file",
                    "baseline",
                )

        if rule.review_by is not None and rule.review_by < today:
            v(
                rule.id,
                f"review_by {rule.review_by} has passed",
                "review the rule, then remove or extend review_by",
                "expiry",
            )
        for exception in rule.exceptions:
            if exception.expires < today:
                v(
                    rule.id,
                    f"exception for {exception.path} expired on {exception.expires}",
                    "remove the exception (fix the code) or extend it with a reason",
                    "expiry",
                )
            if not any(root.glob(exception.path)):
                v(
                    rule.id,
                    f"exception path '{exception.path}' matches no files",
                    "remove the stale exception",
                )

    return violations
