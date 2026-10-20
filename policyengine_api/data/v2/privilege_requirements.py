"""Derive the table privileges v2 connector modules need from their source.

The privilege manifest (``policyengine_api.data.v2.privileges``) declares what
each database role may do. This module reads connector source with ``ast`` and
works out what the code needs, so a test can compare the two without a
database (rule ``api.v2.runtime-privileges-declared``):

- ``reads*.py`` modules need SELECT on every v2 table they use.
- ``creates*.py``, ``updates*.py`` and ``deletes*.py`` modules need INSERT,
  UPDATE or DELETE, plus SELECT: PostgreSQL authorizes the columns an
  ``INSERT ... RETURNING``, an ORM refresh, or an ``UPDATE``/``DELETE ... WHERE``
  reads with SELECT.
- A function that locks rows (``with_for_update``, including ``read=True``
  for ``FOR SHARE``) needs UPDATE on each table it selects, because PostgreSQL
  requires UPDATE privilege for ``SELECT ... FOR UPDATE``/``FOR SHARE``.

A table counts as used when its model class, imported at runtime from
``policyengine_api.data.v2.models``, appears outside annotations. Imports under
``if TYPE_CHECKING:`` and names that appear only in annotations don't count.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from policyengine_api.data.v2.privileges import TablePrivilege

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from pathlib import Path

V2_MODELS_MODULE = "policyengine_api.data.v2.models"

PRIVILEGES_BY_MODULE_KIND: dict[str, frozenset[TablePrivilege]] = {
    "reads": frozenset({TablePrivilege.SELECT}),
    "creates": frozenset({TablePrivilege.INSERT, TablePrivilege.SELECT}),
    "updates": frozenset({TablePrivilege.UPDATE, TablePrivilege.SELECT}),
    "deletes": frozenset({TablePrivilege.DELETE, TablePrivilege.SELECT}),
}


class UnclassifiedConnectorError(ValueError):
    """Raised for a connector module not named reads, creates, updates or deletes."""


@dataclass(frozen=True, order=True)
class RequiredPrivilege:
    """One privilege a connector module needs on one table, and why."""

    table: str
    privilege: TablePrivilege
    connector: str
    reason: str


def connector_kind(path: Path) -> str:
    """Return reads, creates, updates or deletes from the module's file name."""
    for kind in PRIVILEGES_BY_MODULE_KIND:
        if path.stem == kind or path.stem.startswith(f"{kind}_"):
            return kind
    msg = f"{path.name} is not named reads, creates, updates or deletes"
    raise UnclassifiedConnectorError(msg)


def _is_type_checking_block(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _runtime_model_imports(
    module: ast.Module, table_by_model: Mapping[str, str]
) -> dict[str, str]:
    """Return local names bound to v2 model classes at runtime, mapped to tables."""
    tables_by_local_name: dict[str, str] = {}
    for statement in module.body:
        if _is_type_checking_block(statement):
            continue
        for node in ast.walk(statement):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if not node.module.startswith(V2_MODELS_MODULE):
                continue
            for alias in node.names:
                table = table_by_model.get(alias.name)
                if table is not None:
                    tables_by_local_name[alias.asname or alias.name] = table
    return tables_by_local_name


def _annotation_nodes(module: ast.Module) -> set[int]:
    """Return the ids of every node inside an annotation, which never runs SQL."""
    annotation_roots: list[ast.AST] = []
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                annotation_roots.append(node.returns)
            arguments = node.args
            for argument in [
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
                *([arguments.vararg] if arguments.vararg else []),
                *([arguments.kwarg] if arguments.kwarg else []),
            ]:
                if argument.annotation is not None:
                    annotation_roots.append(argument.annotation)
        elif isinstance(node, ast.AnnAssign):
            annotation_roots.append(node.annotation)
    return {id(inner) for root in annotation_roots for inner in ast.walk(root)}


def _used_names(
    nodes: Iterable[ast.AST], excluded_node_ids: set[int]
) -> Iterator[ast.Name]:
    for node in nodes:
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and id(inner) not in excluded_node_ids:
                yield inner


def _locked_tables(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    tables_by_local_name: Mapping[str, str],
) -> set[str]:
    """Return the tables a function locks with ``with_for_update``.

    With ``of=``, the named models are locked; otherwise every model selected or
    joined in the function is, as PostgreSQL locks every table in the FROM list.
    """
    lock_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "with_for_update"
    ]
    if not lock_calls:
        return set()
    locked: set[str] = set()
    for lock_call in lock_calls:
        of_keyword = next(
            (keyword for keyword in lock_call.keywords if keyword.arg == "of"), None
        )
        if of_keyword is not None:
            locked.update(
                tables_by_local_name[name.id]
                for name in _used_names([of_keyword.value], set())
                if name.id in tables_by_local_name
            )
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            called_name = (
                called.id
                if isinstance(called, ast.Name)
                else called.attr
                if isinstance(called, ast.Attribute)
                else None
            )
            if called_name not in {"select", "join", "outerjoin", "select_from"}:
                continue
            locked.update(
                tables_by_local_name[name.id]
                for name in _used_names(node.args, set())
                if name.id in tables_by_local_name
            )
    return locked


def required_privileges(
    path: Path,
    table_by_model: Mapping[str, str],
    *,
    connector: str | None = None,
) -> set[RequiredPrivilege]:
    """Return every privilege the connector module at ``path`` needs, with reasons."""
    label = connector or path.name
    kind = connector_kind(path)
    module = ast.parse(path.read_text(encoding="utf-8"))
    tables_by_local_name = _runtime_model_imports(module, table_by_model)
    annotation_ids = _annotation_nodes(module)
    import_ids = {
        id(inner)
        for node in ast.walk(module)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for inner in ast.walk(node)
    }
    used_tables = {
        tables_by_local_name[name.id]
        for name in _used_names(module.body, annotation_ids | import_ids)
        if name.id in tables_by_local_name
    }
    requirements = {
        RequiredPrivilege(
            table=table,
            privilege=privilege,
            connector=label,
            reason=f"{kind} module uses the table",
        )
        for table in used_tables
        for privilege in PRIVILEGES_BY_MODULE_KIND[kind]
    }
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            requirements.update(
                RequiredPrivilege(
                    table=table,
                    privilege=TablePrivilege.UPDATE,
                    connector=label,
                    reason=f"{node.name} locks rows with with_for_update",
                )
                for table in _locked_tables(node, tables_by_local_name)
            )
    return requirements


def undeclared_requirements(
    requirements: Iterable[RequiredPrivilege],
    declared: Mapping[str, frozenset[TablePrivilege]],
) -> list[RequiredPrivilege]:
    """Return the requirements the declared table privileges don't cover, sorted."""
    return sorted(
        requirement
        for requirement in requirements
        if requirement.privilege not in declared.get(requirement.table, frozenset())
    )
