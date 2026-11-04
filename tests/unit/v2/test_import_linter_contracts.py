"""Proofs for the v2 Import Linter contracts in pyproject.toml.

Each proof writes a fixture package from ``rules/fixtures/<rule id>/``, then
runs the rule's real contract on it, with ``policyengine_api`` renamed to the
fixture package. The bad package must break the contract and the good one must
keep it. The contract keeps only the exceptions the rule allows by design
(``allowed_ignore_imports`` in rules/registry.toml), not its tolerated baseline.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[3]
FIXTURES = PROJECT_ROOT / "rules" / "fixtures"
FIXTURE_PACKAGE = "fixture_api"
APPLICATION_PACKAGE = re.compile(r"\bpolicyengine_api\b")
RUN_IMPORT_LINTER = (
    "import sys; from importlinter.cli import lint_imports_command; "
    "sys.exit(lint_imports_command())"
)


def _registry_rule(rule_id: str) -> dict:
    registry = tomllib.loads((PROJECT_ROOT / "rules/registry.toml").read_text())
    return next(rule for rule in registry["rule"] if rule["id"] == rule_id)


def _renamed(value: object) -> object:
    if isinstance(value, str):
        return APPLICATION_PACKAGE.sub(FIXTURE_PACKAGE, value)
    if isinstance(value, list):
        return [_renamed(item) for item in value]
    return value


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    msg = f"no TOML form for {value!r}"
    raise TypeError(msg)


def _fixture_config(rule_id: str) -> tuple[str, str]:
    """Return the rule's contract id and an Import Linter config for the fixture."""
    enforcer = _registry_rule(rule_id)["enforcer"]
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    settings = pyproject["tool"]["importlinter"]
    contract = next(
        contract
        for contract in settings["contracts"]
        if contract["id"] == enforcer["contract"]
    )
    allowed = set(enforcer.get("allowed_ignore_imports", []))
    fixture_contract = {
        key: _renamed(value)
        for key, value in contract.items()
        if key not in {"ignore_imports", "unmatched_ignore_imports_alerting"}
    }
    kept_exceptions = [
        entry for entry in contract.get("ignore_imports", []) if entry in allowed
    ]
    if kept_exceptions:
        fixture_contract["ignore_imports"] = _renamed(kept_exceptions)
    top_level = {
        key: _renamed(value) for key, value in settings.items() if key != "contracts"
    }
    lines = ["[tool.importlinter]"]
    lines += [f"{key} = {_toml_value(value)}" for key, value in top_level.items()]
    lines += ["", "[[tool.importlinter.contracts]]"]
    lines += [
        f"{key} = {_toml_value(value)}" for key, value in fixture_contract.items()
    ]
    return contract["id"], "\n".join(lines) + "\n"


def _write_package(spec: Path, root: Path) -> None:
    """Write each module the spec lists, with an __init__.py in every package."""
    modules = tomllib.loads(spec.read_text())["modules"]
    for relative_path, source in modules.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        for package in path.parents:
            if package == root:
                break
            (package / "__init__.py").touch()


def _lint_fixture(rule_id: str, fixture: str, root: Path) -> str:
    """Run the rule's contract on a fixture package; return Import Linter's report."""
    contract_id, config = _fixture_config(rule_id)
    _write_package(FIXTURES / rule_id / fixture, root)
    (root / "importlinter.toml").write_text(config)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            RUN_IMPORT_LINTER,
            "--config",
            "importlinter.toml",
            "--contract",
            contract_id,
            "--no-cache",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return completed.stdout + completed.stderr


def _assert_proof(rule_id: str, tmp_path: Path) -> None:
    rejected = _lint_fixture(rule_id, "bad_package.toml", tmp_path / "bad")
    accepted = _lint_fixture(rule_id, "good_package.toml", tmp_path / "good")

    assert "Contracts: 0 kept, 1 broken." in rejected, rejected
    assert "Contracts: 1 kept, 0 broken." in accepted, accepted


def test_rule_proof_import_layers(tmp_path: Path) -> None:
    """Proof for rule api.v2.import-layers."""
    _assert_proof("api.v2.import-layers", tmp_path)


def test_rule_proof_pure_modules_no_database(tmp_path: Path) -> None:
    """Proof for rule api.v2.pure-modules-no-database."""
    _assert_proof("api.v2.pure-modules-no-database", tmp_path)


def test_rule_proof_routes_import_no_database_access(tmp_path: Path) -> None:
    """Proof for rule api.v2.routes-import-no-database-access."""
    _assert_proof("api.v2.routes-import-no-database-access", tmp_path)


def test_rule_proof_types_transformations_no_validators(tmp_path: Path) -> None:
    """Proof for rule api.v2.types-transformations-no-validators."""
    _assert_proof("api.v2.types-transformations-no-validators", tmp_path)


def test_rule_proof_connectors_no_cross_calls(tmp_path: Path) -> None:
    """Proof for rule api.v2.connectors-no-cross-calls."""
    _assert_proof("api.v2.connectors-no-cross-calls", tmp_path)


@pytest.mark.parametrize(
    "rule_id",
    [
        "api.v2.import-layers",
        "api.v2.pure-modules-no-database",
        "api.v2.routes-import-no-database-access",
        "api.v2.types-transformations-no-validators",
        "api.v2.connectors-no-cross-calls",
    ],
)
def test_every_contract_counts_type_checking_imports(rule_id: str) -> None:
    """Imports made only under TYPE_CHECKING count (decided 2026-11-04)."""
    settings = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())["tool"][
        "importlinter"
    ]
    contract_id = _registry_rule(rule_id)["enforcer"]["contract"]

    assert settings.get("exclude_type_checking_imports", False) is False
    assert any(contract["id"] == contract_id for contract in settings["contracts"])
