"""Check that an Import Linter rule matches its contract and its baseline.

An Import Linter contract tolerates existing violations through its
``ignore_imports``. The rule that registers the contract lists the same
entries in its baseline file under ``rules/baselines/`` (code-owned, and the
rules guard lets it only shrink), plus any imports the rule allows by design
in ``enforcer.allowed_ignore_imports``. This module fails the guard when the
two disagree, so an exception can't be added in ``pyproject.toml`` alone.

Standard library only, like the rest of the rules tool.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Any

from scripts.rules.model import Kind, Rule, Violation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _violation(rule: Rule, message: str, fix: str) -> Violation:
    return Violation(rule.id, "enforcer", message, fix)


def contracts(config: Path) -> list[dict[str, Any]]:
    """Return the ``[[tool.importlinter.contracts]]`` tables of a TOML config."""
    if not config.is_file():
        return []
    settings = tomllib.loads(config.read_text()).get("tool", {}).get("importlinter")
    if not isinstance(settings, dict):
        return []
    tables = settings.get("contracts", [])
    return [table for table in tables if isinstance(table, dict)]


def _baseline_entries(rule: Rule, root: Path) -> list[str]:
    if rule.baseline is None:
        return []
    path = root / rule.baseline.file
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def resolve_import_linter(rule: Rule, root: Path) -> list[Violation]:
    """Check the rule's contract exists and its exceptions match the registry."""
    config_name = rule.enforcer.get("config")
    contract_id = rule.enforcer.get("contract")
    if not config_name or not contract_id:
        return []
    config = root / config_name
    if not config.exists():
        return [
            _violation(
                rule,
                f"config file {config_name} does not exist",
                "create it or fix enforcer.config",
            )
        ]
    allowed = rule.enforcer.get("allowed_ignore_imports", [])
    if not isinstance(allowed, list) or not all(
        isinstance(entry, str) for entry in allowed
    ):
        return [
            _violation(
                rule,
                "enforcer.allowed_ignore_imports must be a list of imports written "
                "as Import Linter writes them, such as 'pkg.models -> sqlalchemy'",
                "make it a list of strings",
            )
        ]
    contract = next(
        (item for item in contracts(config) if item.get("id") == contract_id), None
    )
    if contract is None:
        return [
            _violation(
                rule,
                f"{config_name} has no Import Linter contract with id '{contract_id}'",
                "add the contract to [tool.importlinter] or fix enforcer.contract",
            )
        ]

    ignored = [str(entry).strip() for entry in contract.get("ignore_imports", [])]
    expected = set(_baseline_entries(rule, root)) | set(allowed)
    violations = []
    unlisted = [entry for entry in ignored if entry not in expected]
    if unlisted:
        violations.append(
            _violation(
                rule,
                f"contract '{contract_id}' ignores imports that neither the rule's "
                "baseline nor enforcer.allowed_ignore_imports lists: "
                f"{', '.join(unlisted)}",
                "fix the import instead, or list it in the rule's baseline file "
                "under rules/baselines/",
            )
        )
    not_ignored = sorted(expected - set(ignored))
    if not_ignored:
        violations.append(
            _violation(
                rule,
                "the rule's baseline and enforcer.allowed_ignore_imports list "
                f"imports that contract '{contract_id}' does not ignore: "
                f"{', '.join(not_ignored)}",
                "remove them from the baseline, or add them to the contract's "
                "ignore_imports",
            )
        )
    if ignored and contract.get("unmatched_ignore_imports_alerting") != "error":
        violations.append(
            _violation(
                rule,
                f"contract '{contract_id}' has ignore_imports but does not set "
                'unmatched_ignore_imports_alerting = "error", so an exception that '
                "no longer matches would pass",
                "set it on the contract",
            )
        )
    return violations


def unregistered_contracts(rules: Sequence[Rule], root: Path) -> list[Violation]:
    """Return a hidden-rule violation for each contract in pyproject.toml no rule names.

    Import Linter also reads other files, but this repository keeps its
    contracts in pyproject.toml.
    """
    registered = {
        rule.enforcer.get("contract")
        for rule in rules
        if rule.enforcer.kind is Kind.IMPORT_LINTER
        and rule.enforcer.get("config") == "pyproject.toml"
    }
    violations = []
    for contract in contracts(root / "pyproject.toml"):
        contract_id = contract.get("id")
        if not contract_id:
            violations.append(
                Violation(
                    None,
                    "hidden-rule",
                    f"Import Linter contract '{contract.get('name', '')}' in "
                    "pyproject.toml has no id, so no rule can reference it",
                    "give it an id and add a [[rule]] with enforcer.kind = "
                    '"import-linter" that names it',
                )
            )
        elif contract_id not in registered:
            violations.append(
                Violation(
                    None,
                    "hidden-rule",
                    f"Import Linter contract '{contract_id}' in pyproject.toml "
                    "has no rule",
                    'add a [[rule]] with enforcer.kind = "import-linter" and '
                    f'enforcer.contract = "{contract_id}"',
                )
            )
    return violations
