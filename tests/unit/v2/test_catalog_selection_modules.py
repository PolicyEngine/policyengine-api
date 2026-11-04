"""Catalog version selection keeps its database read apart from its validation.

Rule api.catalog.selection-validation-no-database (rules/registry.toml).
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[3]
CATALOG_DIRECTORY = PROJECT_ROOT / "policyengine_api" / "data" / "v2" / "catalog"
VALIDATION_MODULE = CATALOG_DIRECTORY / "catalog_selection_validation.py"
VALIDATION_MODULE_NAME = "policyengine_api.data.v2.catalog.catalog_selection_validation"
PROOF_FIXTURES = (
    PROJECT_ROOT / "rules" / "fixtures" / "api.catalog.selection-validation-no-database"
)
# Never imported by the validation module, even under TYPE_CHECKING.
DATABASE_PACKAGES = ("sqlalchemy", "sqlmodel", "policyengine_api.data.v2.database")
# Imported by the validation module only under TYPE_CHECKING, for annotations.
TABLE_MODELS_PACKAGE = "policyengine_api.data.v2.models"
# Never loaded when the validation module is imported.
RUNTIME_DATABASE_PACKAGES = (*DATABASE_PACKAGES, TABLE_MODELS_PACKAGE)
FORMER_MODULE = "policyengine_api.data.v2.catalog.catalog_selection"
FORMER_MODULE_NAME = re.compile(r"\bcatalog_selection\b")
SEARCHED_DIRECTORIES = (
    ".github",
    "docs",
    "gcp",
    "migrations",
    "policyengine_api",
    "rules",
    "scripts",
    "tests",
)
SEARCHED_SUFFIXES = frozenset(
    {".cfg", ".ini", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}
)
LOADED_MODULES_SCRIPT = """
import importlib
import json
import sys

sys.path[:0] = json.loads(sys.argv[2])
importlib.import_module(sys.argv[1])
print(json.dumps(sorted(sys.modules)))
"""


def _is_type_checking_block(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    condition = node.test
    return (isinstance(condition, ast.Name) and condition.id == "TYPE_CHECKING") or (
        isinstance(condition, ast.Attribute) and condition.attr == "TYPE_CHECKING"
    )


def _imported_from(node: ast.ImportFrom, module_name: str, *, is_package: bool) -> str:
    """Return the absolute module a ``from ... import`` statement reads from."""
    if node.level == 0:
        return node.module or ""
    package_parts = module_name.split(".")
    if not is_package:
        package_parts = package_parts[:-1]
    if node.level > 1:
        package_parts = package_parts[: -(node.level - 1)]
    return ".".join([*package_parts, *([node.module] if node.module else [])])


def _imported_modules(
    tree: ast.Module, module_name: str = "", *, is_package: bool = False
) -> list[tuple[str, bool]]:
    """Return every imported module name, and whether it is imported at runtime.

    ``from package import name`` is recorded as both ``package`` and
    ``package.name``, because ``name`` may be a submodule. Relative imports are
    resolved against ``module_name``.
    """
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
        elif isinstance(node, ast.ImportFrom):
            source = _imported_from(node, module_name, is_package=is_package)
            names = [source, *(f"{source}.{alias.name}" for alias in node.names)]
        else:
            continue
        imported.extend((name, id(node) not in type_checking_imports) for name in names)
    return imported


def _is_within(module_name: str, package: str) -> bool:
    return module_name == package or module_name.startswith(f"{package}.")


def _database_modules_loaded_by(
    module_name: str, search_paths: tuple[Path, ...] = ()
) -> list[str]:
    """List the database modules loaded by importing ``module_name``.

    The import runs in a fresh interpreter, so modules that its parent
    packages' ``__init__`` files load are counted too.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            LOADED_MODULES_SCRIPT,
            module_name,
            json.dumps([str(path) for path in search_paths]),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    loaded = json.loads(completed.stdout.splitlines()[-1])
    return [
        name
        for name in loaded
        if any(_is_within(name, package) for package in RUNTIME_DATABASE_PACKAGES)
    ]


def test_the_validation_module_imports_no_database_code() -> None:
    imported = _imported_modules(
        ast.parse(VALIDATION_MODULE.read_text("utf-8")), VALIDATION_MODULE_NAME
    )

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


def test_importing_the_validation_module_loads_no_database_code() -> None:
    assert _database_modules_loaded_by(VALIDATION_MODULE_NAME) == []


def test_rule_proof_selection_validation_no_database() -> None:
    """Proof for rule api.catalog.selection-validation-no-database."""
    assert _database_modules_loaded_by("bad_catalog_validation", (PROOF_FIXTURES,))
    assert not _database_modules_loaded_by("good_catalog_validation", (PROOF_FIXTURES,))


def test_the_import_helper_resolves_package_and_relative_imports() -> None:
    tree = ast.parse(
        "from policyengine_api.data.v2 import models\n"
        "from .. import database\n"
        "from . import catalog_selection\n"
    )

    imported = {
        module_name
        for module_name, _ in _imported_modules(tree, VALIDATION_MODULE_NAME)
    }

    assert "policyengine_api.data.v2.models" in imported
    assert "policyengine_api.data.v2.database" in imported
    assert FORMER_MODULE in imported


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


def _module_name(path: Path) -> tuple[str, bool]:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    parts = list(relative.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def _imports_the_former_module(path: Path) -> bool:
    module_name, is_package = _module_name(path)
    tree = ast.parse(path.read_text("utf-8"))
    return any(
        _is_within(imported, FORMER_MODULE)
        for imported, _ in _imported_modules(tree, module_name, is_package=is_package)
    )


def test_no_code_imports_the_former_mixed_module() -> None:
    importers = [
        str(path.relative_to(PROJECT_ROOT))
        for directory in ("policyengine_api", "tests", "scripts")
        for path in sorted((PROJECT_ROOT / directory).rglob("*.py"))
        if _imports_the_former_module(path)
    ]

    assert importers == []
    assert not (CATALOG_DIRECTORY / "catalog_selection.py").exists()


def test_no_file_names_the_former_mixed_module() -> None:
    """Catch string references too, such as mock.patch targets and docs."""
    this_file = Path(__file__).resolve()
    naming_files = [
        str(path.relative_to(PROJECT_ROOT))
        for directory in SEARCHED_DIRECTORIES
        for path in sorted((PROJECT_ROOT / directory).rglob("*"))
        if path.suffix in SEARCHED_SUFFIXES
        and path.is_file()
        and path.resolve() != this_file
        and FORMER_MODULE_NAME.search(path.read_text("utf-8", errors="replace"))
    ]

    assert naming_files == []
