"""Parsing for the asserting-tests guard: modules, imports and direct checks.

scripts/rules/asserting_tests.py describes what counts as a check, and
scripts/rules/check_index.py decides which tests check something. Standard
library only.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

SEPARATOR = "::"
PYTEST_CHECKS = frozenset({"raises", "warns", "deprecated_call", "fail"})
ASSERT_PREFIXES = ("assert", "_assert")
# Proof fixtures for the rules: test data that no test runner collects.
EXCLUDED_PREFIXES = ("rules/fixtures/", "scripts/rules/tests/fixtures/")
TEST_DIRECTORY = "tests"
PYTEST = "pytest"
UNITTEST = "unittest"
# Test directories CI runs with unittest discover, which collects only
# TestCase subclasses; pytest collects the rest.
UNITTEST_DIRECTORIES = ("scripts/rules/tests/",)
FUNCTION = "function"
CLASS = "class"
IMPORT = "import"

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class UncheckedTest:
    """A test function that checks nothing."""

    path: str
    line: int
    name: str

    @property
    def entry(self) -> str:
        """The test as a baseline entry: ``<path>::<test>``."""
        return f"{self.path}{SEPARATOR}{self.name}"


def is_test_file(path: str) -> bool:
    """Whether pytest or unittest collects tests from ``path``.

    The rule-proof fixture directories hold test data that no test runner
    collects.
    """
    name = PurePosixPath(path).name
    return (
        name.endswith(".py")
        and (name.startswith("test_") or name.endswith("_test.py"))
        and not path.startswith(EXCLUDED_PREFIXES)
    )


def is_test_code(path: str) -> bool:
    """Whether ``path`` is test code, whose helpers the guard follows."""
    parts = PurePosixPath(path).parts
    return (
        TEST_DIRECTORY in parts[:-1] or parts[-1] == "conftest.py" or is_test_file(path)
    )


def runner_for(path: str) -> str:
    """Return the test runner that collects ``path``'s tests."""
    return UNITTEST if path.startswith(UNITTEST_DIRECTORIES) else PYTEST


def called_name(call: ast.Call) -> str | None:
    """Return the called function's own name: ``f`` for ``f()`` and ``a.b.f()``."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def module_statements(body: Iterable[ast.stmt]) -> Iterator[ast.stmt]:
    """Yield a body's statements, including those in if, try and with blocks."""
    for node in body:
        yield node
        blocks: list[list[ast.stmt]] = []
        if isinstance(node, ast.If):
            blocks = [node.body, node.orelse]
        elif isinstance(node, (ast.Try, ast.TryStar)):
            blocks = [node.body, node.orelse, node.finalbody]
            blocks += [handler.body for handler in node.handlers]
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            blocks = [node.body]
        for block in blocks:
            yield from module_statements(block)


def assigned_names(node: ast.stmt) -> list[str]:
    """Return the plain names an assignment statement binds."""
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets = [node.target]
    else:
        return []
    return [target.id for target in targets if isinstance(target, ast.Name)]


def dunder_test(body: Iterable[ast.stmt]) -> bool | None:
    """Return what a module or class body sets ``__test__`` to, if it sets it."""
    for node in body:
        if "__test__" in assigned_names(node):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, bool):
                return value.value
    return None


def decorator_names(node: FunctionNode | ast.ClassDef) -> set[str]:
    """Return each decorator's own name: ``fixture`` for ``@pytest.fixture()``."""
    names = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def defines_constructor(node: ast.ClassDef) -> bool:
    """Whether pytest refuses the class: an ``__init__``, ``__new__`` or dataclass."""
    return "dataclass" in decorator_names(node) or any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name in {"__init__", "__new__"}
        for statement in node.body
    )


def module_path(importer: str, module: str | None, level: int) -> str | None:
    """Return the repository path stem ``a/b/c`` an import names, if it can tell."""
    if level == 0:
        return module.replace(".", "/") if module else None
    package = PurePosixPath(importer).parent
    for _ in range(level - 1):
        package = package.parent
    stem = package.as_posix() if package.as_posix() != "." else ""
    if module:
        dotted = module.replace(".", "/")
        stem = f"{stem}/{dotted}" if stem else dotted
    return stem or None


def parameters(function: FunctionNode | ast.Lambda) -> set[str]:
    """Return the names of a function's or lambda's parameters."""
    arguments = function.args
    names = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *([arguments.vararg] if arguments.vararg else []),
        *([arguments.kwarg] if arguments.kwarg else []),
    ]
    return {argument.arg for argument in names}


@dataclass
class Bindings:
    """The names imports bind in one scope: a module, or a function's body."""

    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    modules: dict[str, str] = field(default_factory=dict)
    star_sources: list[str] = field(default_factory=list)
    pytest_modules: set[str] = field(default_factory=lambda: {"pytest"})
    pytest_names: set[str] = field(default_factory=set)
    assert_names: set[str] = field(default_factory=set)

    def add(self, path: str, node: ast.Import | ast.ImportFrom) -> None:
        """Record what an import statement in module ``path`` binds."""
        if isinstance(node, ast.Import):
            self._add_import(node)
        else:
            self._add_from_import(path, node)

    def _add_import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "pytest":
                self.pytest_modules.add(alias.asname or "pytest")
            elif alias.asname:
                self.modules[alias.asname] = alias.name.replace(".", "/")

    def _add_from_import(self, path: str, node: ast.ImportFrom) -> None:
        stem = module_path(path, node.module, node.level)
        from_pytest = node.module == "pytest" and node.level == 0
        for alias in node.names:
            bound = alias.asname or alias.name
            if alias.name.startswith(ASSERT_PREFIXES):
                self.assert_names.add(bound)
            if from_pytest:
                if alias.name in PYTEST_CHECKS:
                    self.pytest_names.add(bound)
            elif stem is not None and alias.name == "*":
                self.star_sources.append(stem)
            elif stem is not None:
                self.imports[bound] = (stem, alias.name)

    def bound_names(self) -> set[str]:
        """Return every name these imports bind, apart from star imports."""
        return (
            set(self.imports)
            | set(self.modules)
            | (self.pytest_modules - {"pytest"})
            | self.pytest_names
            | self.assert_names
        )


@dataclass(eq=False)
class ParsedModule:
    """What the guard needs from one parsed module.

    ``last_kinds`` says whether a module-level name was last bound by a
    function, a class or an import, in source order.
    """

    path: str
    tree: ast.Module
    functions: dict[str, FunctionNode]
    classes: dict[str, ast.ClassDef]
    bindings: Bindings
    last_kinds: dict[str, str]
    runner: str


@dataclass(eq=False)
class ParsedClass:
    """A class and the module that defines it."""

    module: ParsedModule
    node: ast.ClassDef

    @property
    def key(self) -> tuple[str, int, int]:
        """Identify the class across lookups: its module path and position."""
        return (self.module.path, self.node.lineno, self.node.col_offset)


def parse_module(path: str, text: str) -> ParsedModule:
    """Parse ``text`` as module ``path``; raise SyntaxError if it doesn't parse."""
    tree = ast.parse(text.removeprefix("﻿"), filename=path)
    functions: dict[str, FunctionNode] = {}
    classes: dict[str, ast.ClassDef] = {}
    last_kinds: dict[str, str] = {}
    bindings = Bindings()
    for node in module_statements(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
            last_kinds[node.name] = FUNCTION
        elif isinstance(node, ast.ClassDef):
            classes[node.name] = node
            last_kinds[node.name] = CLASS
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bindings.add(path, node)
            for alias in node.names:
                if alias.name != "*":
                    bound = alias.asname or alias.name.split(".")[0]
                    last_kinds[bound] = IMPORT
    return ParsedModule(
        path, tree, functions, classes, bindings, last_kinds, runner_for(path)
    )


def _raises_assertion_error(node: ast.Raise) -> bool:
    raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return isinstance(raised, ast.Name) and raised.id == "AssertionError"


def is_direct_check(
    node: ast.AST, scopes: tuple[Bindings, ...], stand_in_calls: frozenset[int]
) -> bool:
    """Whether ``node`` is itself a check, without following any helper.

    ``self.fail`` is unittest's only when the call isn't in a stand-in, whose
    ``self`` is the stand-in.
    """
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Raise):
        return _raises_assertion_error(node)
    if not isinstance(node, ast.Call):
        return False
    name = called_name(node)
    function = node.func
    owner = (
        function.value.id
        if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name)
        else None
    )
    return name is not None and (
        name.startswith(ASSERT_PREFIXES)
        or (owner == "self" and name == "fail" and id(node) not in stand_in_calls)
        or any(
            (owner in scope.pytest_modules and name in PYTEST_CHECKS)
            or (
                isinstance(function, ast.Name)
                and (name in scope.pytest_names or name in scope.assert_names)
            )
            for scope in scopes
        )
    )
