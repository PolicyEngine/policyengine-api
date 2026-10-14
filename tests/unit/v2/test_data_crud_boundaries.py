"""Structural checks for API v2 service and database-connector modules."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parents[3]
SERVICES_ROOT = PROJECT_ROOT / "policyengine_api" / "services" / "v2"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _called_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    return modules


def _has_database_query_dependency(path: Path) -> bool:
    return any(
        module == "sqlalchemy"
        or module.startswith("sqlalchemy.")
        or module == "sqlmodel"
        or module.startswith("sqlmodel.")
        for module in _imported_modules(path)
    )


def _discover(*patterns: str) -> list[str]:
    """Modules under SERVICES_ROOT matching any pattern, as sorted relative paths.

    Discovering modules (rather than listing them) means a new resource package
    is checked automatically. An empty result fails at collection, because
    pytest silently skips a test whose parameter list is empty.
    """
    paths = sorted(
        {
            path.relative_to(SERVICES_ROOT).as_posix()
            for pattern in patterns
            for path in SERVICES_ROOT.glob(pattern)
        }
    )
    assert paths, f"no modules under {SERVICES_ROOT} match {patterns}"
    return paths


MUTATION_CONNECTORS = _discover(
    "*/database_connectors/creates*.py",
    "*/database_connectors/updates*.py",
    "*/database_connectors/deletes*.py",
)
READ_CONNECTORS = _discover("*/database_connectors/reads*.py")
VALIDATION_AND_TRANSFORMATION_MODULES = _discover(
    "*/validators.py", "*/transformations.py"
)
DATABASE_SESSION_MODULES = _discover("*/database_session.py")


def test_every_connector_module_is_classified() -> None:
    connectors = {
        path
        for path in _discover("*/database_connectors/*.py")
        if not path.endswith("/__init__.py")
    }
    classified = set(MUTATION_CONNECTORS) | set(READ_CONNECTORS)
    assert connectors - classified == set(), (
        "connector modules must be named creates, reads, updates or deletes "
        "(optionally with a _suffix) so the boundary checks below cover them"
    )


@pytest.mark.parametrize("relative_path", MUTATION_CONNECTORS)
def test_mutation_connectors_contain_no_database_reads(relative_path: str) -> None:
    calls = _called_names(SERVICES_ROOT / relative_path)
    assert "select" not in calls
    assert "get" not in calls


@pytest.mark.parametrize("relative_path", READ_CONNECTORS)
def test_read_connectors_contain_no_database_mutations(relative_path: str) -> None:
    calls = _called_names(SERVICES_ROOT / relative_path)
    assert calls.isdisjoint({"insert", "add", "add_all", "delete"})


@pytest.mark.parametrize("relative_path", VALIDATION_AND_TRANSFORMATION_MODULES)
def test_validation_and_transformation_modules_have_no_database_query_dependency(
    relative_path: str,
) -> None:
    assert not _has_database_query_dependency(SERVICES_ROOT / relative_path)


def test_rule_proof_validators_transformations_no_db() -> None:
    """Proof for rule api.v2.validators-transformations-no-db (rules/registry.toml)."""
    fixtures = PROJECT_ROOT / "rules/fixtures/api.v2.validators-transformations-no-db"
    assert _has_database_query_dependency(fixtures / "bad_validators.py")
    assert not _has_database_query_dependency(fixtures / "good_validators.py")


@pytest.mark.parametrize("relative_path", DATABASE_SESSION_MODULES)
def test_database_session_modules_do_not_construct_queries(
    relative_path: str,
) -> None:
    calls = _called_names(SERVICES_ROOT / relative_path)
    assert calls.isdisjoint({"select", "insert", "update", "delete", "exec"})


@pytest.mark.parametrize(
    "relative_path",
    (
        "identity/services.py",
        "legacy_refs/services.py",
        "user_accounts/services.py",
        "user_households/services.py",
        "user_policies/services.py",
        "user_reports/services.py",
        "user_simulations/services.py",
    ),
)
def test_user_services_construct_no_sql(relative_path: str) -> None:
    calls = _called_names(SERVICES_ROOT / relative_path)
    imports = _imported_modules(SERVICES_ROOT / relative_path)
    assert calls.isdisjoint({"select", "insert", "update", "delete", "exec", "text"})
    assert not any(module.startswith("sqlalchemy") for module in imports)
