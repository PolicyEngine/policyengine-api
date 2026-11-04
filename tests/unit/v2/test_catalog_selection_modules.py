"""Catalog version selection keeps its database read apart from its validation."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[3]
CATALOG_DIRECTORY = PROJECT_ROOT / "policyengine_api" / "data" / "v2" / "catalog"
VALIDATION_MODULE = CATALOG_DIRECTORY / "catalog_selection_validation.py"
READS_MODULE = CATALOG_DIRECTORY / "catalog_selection_reads.py"
DATABASE_PACKAGES = ("sqlalchemy", "sqlmodel", "policyengine_api.data.v2.database")
TABLE_MODELS_PACKAGE = "policyengine_api.data.v2.models"


def _is_type_checking_block(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    condition = node.test
    return (isinstance(condition, ast.Name) and condition.id == "TYPE_CHECKING") or (
        isinstance(condition, ast.Attribute) and condition.attr == "TYPE_CHECKING"
    )


def _imported_modules(tree: ast.Module) -> list[tuple[str, bool]]:
    """Return every imported module name, and whether it is imported at runtime."""
    type_checking_imports = {
        id(import_node)
        for block in ast.walk(tree)
        if _is_type_checking_block(block)
        for statement in block.body
        for import_node in ast.walk(statement)
    }
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        imported.extend((name, id(node) not in type_checking_imports) for name in names)
    return imported


def _is_within(module_name: str, package: str) -> bool:
    return module_name == package or module_name.startswith(f"{package}.")


def test_the_validation_module_imports_no_database_code() -> None:
    imported = _imported_modules(ast.parse(VALIDATION_MODULE.read_text("utf-8")))

    database_imports = [
        module_name
        for module_name, _ in imported
        if any(_is_within(module_name, package) for package in DATABASE_PACKAGES)
    ]
    runtime_table_model_imports = [
        module_name
        for module_name, at_runtime in imported
        if at_runtime and _is_within(module_name, TABLE_MODELS_PACKAGE)
    ]

    assert database_imports == []
    assert runtime_table_model_imports == []


def test_the_reads_module_holds_the_catalog_query() -> None:
    from policyengine_api.data.v2.catalog import (
        catalog_selection_reads,
        catalog_selection_validation,
    )

    reads_functions = {
        name
        for name, member in inspect.getmembers(catalog_selection_reads)
        if inspect.isfunction(member)
        and member.__module__ == catalog_selection_reads.__name__
    }
    validation_functions = {
        name
        for name, member in inspect.getmembers(catalog_selection_validation)
        if inspect.isfunction(member)
        and member.__module__ == catalog_selection_validation.__name__
    }

    assert reads_functions == {"select_catalog"}
    assert validation_functions == {"validate_policyengine_version"}


def _imports_the_former_mixed_module(tree: ast.Module) -> bool:
    former_module = "policyengine_api.data.v2.catalog.catalog_selection"
    if any(module_name == former_module for module_name, _ in _imported_modules(tree)):
        return True
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "policyengine_api.data.v2.catalog"
        and any(alias.name == "catalog_selection" for alias in node.names)
        for node in ast.walk(tree)
    )


def test_no_code_imports_the_former_mixed_module() -> None:
    importers = [
        str(path.relative_to(PROJECT_ROOT))
        for directory in ("policyengine_api", "tests", "scripts")
        for path in sorted((PROJECT_ROOT / directory).rglob("*.py"))
        if _imports_the_former_mixed_module(ast.parse(path.read_text("utf-8")))
    ]

    assert importers == []
    assert not (CATALOG_DIRECTORY / "catalog_selection.py").exists()
