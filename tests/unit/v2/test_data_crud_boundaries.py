"""Structural checks for API v2 service and database-connector modules."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parents[3]
DATA_ROOT = PROJECT_ROOT / "policyengine_api" / "data" / "v2"
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


@pytest.mark.parametrize(
    "relative_path",
    (
        "user_policies/creates.py",
        "user_policies/updates.py",
        "user_policies/deletes.py",
    ),
)
def test_existing_mutation_modules_contain_no_database_reads(
    relative_path: str,
) -> None:
    calls = _called_names(DATA_ROOT / relative_path)
    assert "select" not in calls
    assert "get" not in calls


def test_existing_read_module_contains_no_database_mutations() -> None:
    calls = _called_names(DATA_ROOT / "user_policies/reads.py")
    assert calls.isdisjoint({"insert", "add", "add_all", "delete"})


def test_policy_create_connectors_contain_no_database_reads() -> None:
    calls = _called_names(SERVICES_ROOT / "policies/database_connectors/creates.py")
    assert "select" not in calls
    assert "get" not in calls


@pytest.mark.parametrize(
    "relative_path",
    (
        "policies/database_connectors/reads.py",
        "metadata/database_connectors/reads.py",
        "metadata/database_connectors/reads_datasets.py",
        "metadata/database_connectors/reads_parameter_tree.py",
        "metadata/database_connectors/reads_parameters.py",
        "metadata/database_connectors/reads_regions.py",
        "metadata/database_connectors/reads_variables.py",
    ),
)
def test_read_connectors_contain_no_database_mutations(relative_path: str) -> None:
    calls = _called_names(SERVICES_ROOT / relative_path)
    assert calls.isdisjoint({"insert", "add", "add_all", "delete"})


@pytest.mark.parametrize(
    "relative_path",
    (
        "policies/validators.py",
        "policies/transformations.py",
        "metadata/validators.py",
        "metadata/transformations.py",
    ),
)
def test_validation_and_transformation_modules_have_no_database_query_dependency(
    relative_path: str,
) -> None:
    imports = _imported_modules(SERVICES_ROOT / relative_path)
    assert not any(
        module == "sqlalchemy"
        or module.startswith("sqlalchemy.")
        or module == "sqlmodel"
        or module.startswith("sqlmodel.")
        for module in imports
    )


@pytest.mark.parametrize(
    "relative_path",
    ("policies/database_session.py", "metadata/database_session.py"),
)
def test_database_session_modules_do_not_construct_queries(
    relative_path: str,
) -> None:
    calls = _called_names(SERVICES_ROOT / relative_path)
    assert calls.isdisjoint({"select", "insert", "update", "delete", "exec"})
