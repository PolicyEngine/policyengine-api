"""Semantic validation of a parsed registry against the repository tree."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any

from scripts.rules.model import Kind, Registry, Rule, Status, Tier, Violation
from scripts.rules.resolve import PROOF_CI_FIELDS, node_exists

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


def _schema_violation(rule: Rule, message: str, fix: str) -> Violation:
    """Report a schema problem with one rule."""
    return Violation(rule.id, "schema", message, fix)


def _status_conflicts(rule: Rule) -> list[Violation]:
    """Check that the rule's status fits its enforcer, CI wiring and baseline."""
    kind, status = rule.enforcer.kind, rule.status
    violations = []
    if status is Status.DOC_ONLY and kind is not Kind.NONE:
        violations.append(
            _schema_violation(
                rule,
                "doc-only rules have no enforcer",
                'set enforcer.kind = "none", or pick a stronger status',
            )
        )
    if status is Status.DOC_ONLY and rule.ci:
        violations.append(
            _schema_violation(
                rule,
                "doc-only rules have no CI wiring",
                "remove rule.ci, or pick a stronger status",
            )
        )
    if kind is Kind.NONE and status not in (Status.DOC_ONLY, Status.ADVISORY):
        violations.append(
            _schema_violation(
                rule,
                f"status {status} needs an enforcer",
                "add [rule.enforcer] or use doc-only/advisory",
            )
        )
    if status in (Status.ENFORCED, Status.RATCHETED) and not rule.ci:
        violations.append(
            _schema_violation(
                rule, f"{status} rules must run in CI", "add a [[rule.ci]] reference"
            )
        )
    if status is Status.RATCHETED and rule.baseline is None:
        violations.append(
            _schema_violation(
                rule,
                "ratcheted rules need a baseline",
                "add [rule.baseline] or use enforced",
            )
        )
    if rule.baseline is not None and status is not Status.RATCHETED:
        violations.append(
            _schema_violation(
                rule,
                "only ratcheted rules may have a baseline",
                'remove [rule.baseline] or set status = "ratcheted"',
            )
        )
    return violations


def _checker_conflicts(rule: Rule) -> list[Violation]:
    """Check that the rule's enforcer kind suits its tier and baseline."""
    kind, tier = rule.enforcer.kind, rule.tier
    violations = []
    if kind is Kind.RUFF and rule.baseline is not None:
        violations.append(
            _schema_violation(
                rule,
                "ruff is never ratcheted",
                "remove the baseline and fix every violation in a standalone PR "
                "that also changes the ruff select list",
            )
        )
    if tier is Tier.JUDGMENT and kind not in (Kind.LLM_REVIEW, Kind.NONE):
        violations.append(
            _schema_violation(
                rule,
                "judgment rules are enforced by review, not by a mechanical checker",
                'use enforcer.kind = "llm-review" or "none"',
            )
        )
    if kind is Kind.LLM_REVIEW and tier is not Tier.JUDGMENT:
        violations.append(
            _schema_violation(
                rule,
                "llm-review only enforces judgment rules",
                'set tier = "judgment"',
            )
        )
    return violations


def _validate_cross_fields(rule: Rule) -> list[Violation]:
    return _status_conflicts(rule) + _checker_conflicts(rule)


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
    named = [key for key in PROOF_CI_FIELDS if key in fields]
    if named and len(named) != len(PROOF_CI_FIELDS):
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


def _validate_agents(registry: Registry, root: Path) -> list[Violation]:
    """Check that every agent instruction file named in ``[agents]`` exists."""
    if registry.agents is None:
        return []
    return [
        Violation(
            None,
            "schema",
            f"agents file {path} does not exist",
            "fix [agents] or create the file",
        )
        for path in (registry.agents.instructions, *registry.agents.adapters)
        if path and not (root / path).is_file()
    ]


def _validate_ci_scripts(registry: Registry, root: Path) -> list[Violation]:
    """Check that the ``[ci_scripts]`` directory and baseline files exist."""
    config = registry.ci_scripts
    if config is None:
        return []
    violations = []
    if config.scripts_dir and not (root / config.scripts_dir).is_dir():
        violations.append(
            Violation(
                None,
                "schema",
                f"ci_scripts.scripts_dir {config.scripts_dir} does not exist",
                "fix [ci_scripts]",
            )
        )
    violations.extend(
        Violation(
            None,
            "schema",
            f"ci_scripts baseline {path} does not exist",
            "create it (it may be empty)",
        )
        for path in (
            config.multiline_baseline,
            config.untested_baseline,
            config.shellcheck_baseline,
        )
        if path and not (root / path).is_file()
    )
    return violations


def _duplicate_ids(registry: Registry, category_ids: list[str]) -> list[Violation]:
    """Report each category id, then each rule id, that is used more than once."""
    violations = [
        Violation(
            None,
            "schema",
            f"duplicate category '{duplicate}'",
            "give each category a unique id",
        )
        for duplicate in sorted({c for c in category_ids if category_ids.count(c) > 1})
    ]
    rule_ids = [rule.id for rule in registry.rules]
    violations.extend(
        Violation(
            duplicate, "schema", "duplicate rule id", "give each rule a unique id"
        )
        for duplicate in sorted({r for r in rule_ids if rule_ids.count(r) > 1})
    )
    return violations


def _validate_identity(
    rule: Rule, root: Path, category_ids: list[str]
) -> list[Violation]:
    """Check the rule's id, category, rationale link and scope globs."""
    violations = []
    if rule.id and not RULE_ID.match(rule.id):
        violations.append(
            _schema_violation(
                rule,
                "id must be lowercase dotted, e.g. 'api.v2.routes-no-sql'",
                "rename the rule",
            )
        )
    if rule.category not in category_ids:
        violations.append(
            _schema_violation(
                rule,
                f"unknown category '{rule.category}'",
                f"use one of {category_ids} or add a [[category]]",
            )
        )
    rationale_path = rule.rationale.split("#", 1)[0]
    if rationale_path and not (root / rationale_path).exists():
        violations.append(
            _schema_violation(
                rule,
                f"rationale {rationale_path} does not exist",
                "link an existing doc",
            )
        )
    violations.extend(
        _schema_violation(rule, f"scope '{pattern}' matches no files", "fix the glob")
        for pattern in rule.scope
        if not any(root.glob(pattern))
    )
    return violations


def _validate_baseline(rule: Rule, root: Path) -> list[Violation]:
    """Check that a ratcheted rule's baseline file exists and matches its count."""
    if rule.baseline is None:
        return []
    path = root / rule.baseline.file
    if not path.is_file():
        return [
            Violation(
                rule.id,
                "baseline",
                f"baseline file {rule.baseline.file} does not exist",
                "create it",
            )
        ]
    if baseline_entries(path) != rule.baseline.count:
        return [
            Violation(
                rule.id,
                "baseline",
                f"baseline count is {rule.baseline.count} but "
                f"{rule.baseline.file} lists {baseline_entries(path)}",
                "make the count match the file",
            )
        ]
    return []


def _validate_expiry(rule: Rule, root: Path, today: date) -> list[Violation]:
    """Check the review date and each exception's expiry and path on ``today``."""
    violations = []
    if rule.review_by is not None and rule.review_by < today:
        violations.append(
            Violation(
                rule.id,
                "expiry",
                f"review_by {rule.review_by} has passed",
                "review the rule, then remove or extend review_by",
            )
        )
    for exception in rule.exceptions:
        if exception.expires < today:
            violations.append(
                Violation(
                    rule.id,
                    "expiry",
                    f"exception for {exception.path} expired on {exception.expires}",
                    "remove the exception (fix the code) or extend it with a reason",
                )
            )
        if not any(root.glob(exception.path)):
            violations.append(
                _schema_violation(
                    rule,
                    f"exception path '{exception.path}' matches no files",
                    "remove the stale exception",
                )
            )
    return violations


def _validate_rule(
    rule: Rule, root: Path, category_ids: list[str], today: date
) -> list[Violation]:
    """Run every per-rule check, in the order the guard reports them."""
    return [
        *_validate_identity(rule, root, category_ids),
        *_validate_enforcer(rule),
        *_validate_cross_fields(rule),
        *_validate_proof(rule, root),
        *_validate_baseline(rule, root),
        *_validate_expiry(rule, root, today),
    ]


def validate(registry: Registry, root: Path, today: date) -> list[Violation]:
    """Check the registry's fields and file references against the tree at ``root``.

    ``today`` decides whether review dates and exceptions have expired.
    """
    category_ids = [category.id for category in registry.categories]
    violations = [
        *_validate_agents(registry, root),
        *_validate_ci_scripts(registry, root),
        *_duplicate_ids(registry, category_ids),
    ]
    for rule in registry.rules:
        violations.extend(_validate_rule(rule, root, category_ids, today))
    return violations
