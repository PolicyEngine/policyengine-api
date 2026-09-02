"""Structural checks for API v2 database CRUD modules."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parents[3]
DATA_ROOT = PROJECT_ROOT / "policyengine_api" / "data" / "v2"
SERVICE_ROOT = PROJECT_ROOT / "policyengine_api" / "services" / "v2" / "policies"


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
        "policies/creates.py",
        "user_policies/creates.py",
        "user_policies/updates.py",
        "user_policies/deletes.py",
    ),
)
def test_mutation_modules_contain_no_database_reads(relative_path: str) -> None:
    calls = _called_names(DATA_ROOT / relative_path)
    assert "select" not in calls
    assert "get" not in calls


@pytest.mark.parametrize(
    "relative_path",
    (
        "policies/reads.py",
        "user_policies/reads.py",
        "metadata/reads.py",
        "metadata/reads_datasets.py",
        "metadata/reads_models.py",
        "metadata/reads_parameter_tree.py",
        "metadata/reads_parameters.py",
        "metadata/reads_regions.py",
        "metadata/reads_variables.py",
    ),
)
def test_read_modules_contain_no_database_mutations(relative_path: str) -> None:
    calls = _called_names(DATA_ROOT / relative_path)
    assert calls.isdisjoint({"insert", "add", "add_all", "delete"})


@pytest.mark.parametrize(
    "filename",
    ("catalog_validation.py", "canonicalization.py"),
)
def test_policy_validation_and_identity_modules_have_no_database_dependency(
    filename: str,
) -> None:
    imports = _imported_modules(SERVICE_ROOT / filename)
    assert not any(
        module == "sqlalchemy"
        or module.startswith("sqlalchemy.")
        or module == "sqlmodel"
        or module.startswith("sqlmodel.")
        for module in imports
    )
