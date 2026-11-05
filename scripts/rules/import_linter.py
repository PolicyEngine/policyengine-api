"""Check that an Import Linter rule matches its contract and its baseline.

An Import Linter contract tolerates existing violations through its
``ignore_imports``. The rule that registers the contract lists the same
entries in its baseline file under ``rules/baselines/`` (code-owned; the rules
guard stops its count growing), plus any imports the rule allows by design in
``enforcer.allowed_ignore_imports``. The rule also pins the rest of the
contract, and the top-level ``[tool.importlinter]`` settings, with
``enforcer.contract_sha256``. This module fails the guard when the registry
and ``pyproject.toml`` disagree, so neither an exception nor a narrower
contract can be made in ``pyproject.toml`` alone.

Standard library only, like the rest of the rules tool.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from typing import TYPE_CHECKING, Any

from scripts.rules.makefile import job_make_commands
from scripts.rules.model import Kind, Rule, Violation
from scripts.rules.workflows import parse_jobs

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class ConfigNotTomlError(ValueError):
    """The named Import Linter config is not a TOML file."""


def _violation(rule: Rule, message: str, fix: str) -> Violation:
    return Violation(rule.id, "enforcer", message, fix)


def _settings(config: Path) -> dict[str, Any]:
    """Return ``[tool.importlinter]`` from a TOML config, or ``{}`` if absent."""
    if not config.is_file():
        return {}
    try:
        document = tomllib.loads(config.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigNotTomlError(config.name) from error
    settings = document.get("tool", {}).get("importlinter")
    return settings if isinstance(settings, dict) else {}


def _contract_tables(settings: dict[str, Any]) -> list[dict[str, Any]]:
    tables = settings.get("contracts", [])
    return [table for table in tables if isinstance(table, dict)]


def contracts(config: Path) -> list[dict[str, Any]]:
    """Return the ``[[tool.importlinter.contracts]]`` tables of a TOML config."""
    try:
        return _contract_tables(_settings(config))
    except ConfigNotTomlError:
        return []


def contract_fingerprint(settings: dict[str, Any], contract: dict[str, Any]) -> str:
    """Return the SHA-256 that a rule's ``enforcer.contract_sha256`` must equal.

    It covers the top-level settings and every contract field except
    ``ignore_imports``, which the baseline and ``allowed_ignore_imports`` pin.
    """
    definition = {
        "settings": {
            key: value for key, value in settings.items() if key != "contracts"
        },
        "contract": {
            key: value for key, value in contract.items() if key != "ignore_imports"
        },
    }
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


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


def _exception_violations(
    rule: Rule, root: Path, contract_id: str, contract: dict[str, Any]
) -> list[Violation]:
    """Compare the contract's ignore_imports with the rule's baseline and allowances."""
    ignored = [str(entry).strip() for entry in contract.get("ignore_imports", [])]
    allowed = rule.enforcer.get("allowed_ignore_imports", [])
    expected = set(_baseline_entries(rule, root)) | set(allowed)
    violations = [
        _violation(
            rule,
            f"contract '{contract_id}' ignores {entry}, a wildcard that would also "
            "ignore imports added later",
            "list each import by its full module names",
        )
        for entry in ignored
        if "*" in entry
    ]
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


def resolve_import_linter(rule: Rule, root: Path) -> list[Violation]:
    """Check the rule's contract exists, is the one it pins, and has its exceptions."""
    config_name = rule.enforcer.get("config")
    contract_id = rule.enforcer.get("contract")
    if not config_name or not contract_id:
        return [
            _violation(
                rule,
                "enforcer.config and enforcer.contract must name the config file "
                "and the contract's id",
                'set both, for example config = "pyproject.toml"',
            )
        ]
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
    try:
        settings = _settings(config)
    except ConfigNotTomlError:
        return [
            _violation(
                rule,
                f"{config_name} is not a TOML file, so the rules guard can't read "
                "its contracts",
                "keep the Import Linter contracts in [tool.importlinter] in "
                "pyproject.toml",
            )
        ]
    contract = next(
        (
            table
            for table in _contract_tables(settings)
            if table.get("id") == contract_id
        ),
        None,
    )
    if contract is None:
        return [
            _violation(
                rule,
                f"{config_name} has no Import Linter contract with id '{contract_id}'",
                "add the contract to [tool.importlinter] or fix enforcer.contract",
            )
        ]

    violations = []
    pinned = rule.enforcer.get("contract_sha256") or ""
    actual = contract_fingerprint(settings, contract)
    if pinned != actual:
        violations.append(
            _violation(
                rule,
                f"contract '{contract_id}' is not the definition the rule pins "
                f"(enforcer.contract_sha256 is {pinned or 'empty'}, the contract's "
                f"is {actual})",
                "if the change is intended, set enforcer.contract_sha256 = "
                f'"{actual}" in rules/registry.toml',
            )
        )
    violations += _exception_violations(rule, root, contract_id, contract)
    violations += _ci_command_violations(rule, root, config_name)
    return violations


def _ci_command_violations(rule: Rule, root: Path, config_name: str) -> list[Violation]:
    """Require each CI job to run every contract, with failures failing the job.

    The registry's invocation check only looks for a substring, which an
    added ``--contract`` or ``|| true`` would still contain. The commands of
    the make targets a job runs count as the job's, and a recipe's ``-``
    prefix, which ignores the command's failure, doesn't match.
    """
    exact = re.compile(
        rf"^(?:uv run .*\s)?lint-imports --config {re.escape(config_name)}$"
    )
    violations = []
    for reference in rule.ci:
        workflow = root / reference.workflow
        if not workflow.is_file():
            continue
        job = parse_jobs(workflow.read_text())[0].get(reference.job)
        if job is None:
            continue
        violations.extend(
            _violation(
                rule,
                f"job '{reference.job}' in {reference.workflow} runs Import Linter "
                f"as '{command}', which may skip contracts or ignore failures",
                f"run exactly 'lint-imports --config {config_name}', optionally "
                "after 'uv run ...'",
            )
            for command in (
                *(line.strip() for line in job.run_text.splitlines()),
                *job_make_commands(root, job.run_text),
            )
            if "lint-imports" in command and not exact.match(command)
        )
    return violations


def unregistered_contracts(rules: Sequence[Rule], root: Path) -> list[Violation]:
    """Return a hidden-rule violation for each contract in pyproject.toml no rule names.

    Import Linter also reads other files, but this repository keeps its
    contracts in pyproject.toml, and CI passes it with --config.
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
