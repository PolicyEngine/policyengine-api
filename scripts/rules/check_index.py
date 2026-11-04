"""Which test functions check something: the analysis behind asserting-tests.

``CheckIndex`` reads test modules with ``ast``, finds the tests pytest and
unittest collect from them, and decides whether each one checks something,
following the helpers it calls. scripts/rules/asserting_tests.py describes
what counts as a check and holds the rule. Standard library only.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
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
MAX_REEXPORT_DEPTH = 5

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


def _is_test_code(path: str) -> bool:
    """Whether ``path`` is test code, whose helpers the guard follows."""
    parts = PurePosixPath(path).parts
    return (
        TEST_DIRECTORY in parts[:-1] or parts[-1] == "conftest.py" or is_test_file(path)
    )


def _called_name(call: ast.Call) -> str | None:
    """Return the called function's own name: ``f`` for ``f()`` and ``a.b.f()``."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _raises_assertion_error(node: ast.Raise) -> bool:
    raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return isinstance(raised, ast.Name) and raised.id == "AssertionError"


def _module_statements(body: Iterable[ast.stmt]) -> Iterator[ast.stmt]:
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
            yield from _module_statements(block)


def _dunder_test(body: Iterable[ast.stmt]) -> bool | None:
    """Return what a module or class body sets ``__test__`` to, if it sets it."""
    for node in body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "__test__"
            for target in targets
        ):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, bool):
                return value.value
    return None


def _decorator_names(node: FunctionNode | ast.ClassDef) -> set[str]:
    """Return each decorator's own name: ``fixture`` for ``@pytest.fixture()``."""
    names = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _defines_constructor(node: ast.ClassDef) -> bool:
    """Whether pytest refuses the class: it has an ``__init__`` or ``__new__``."""
    return "dataclass" in _decorator_names(node) or any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name in {"__init__", "__new__"}
        for statement in node.body
    )


def _module_path(importer: str, module: str | None, level: int) -> str | None:
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


@dataclass
class _Bindings:
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
        stem = _module_path(path, node.module, node.level)
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
        """Return every name these imports bind."""
        return (
            set(self.imports)
            | set(self.modules)
            | self.pytest_modules
            | self.pytest_names
            | self.assert_names
        )


@dataclass(eq=False)
class _Module:
    """What the guard needs from one parsed module."""

    path: str
    tree: ast.Module
    functions: dict[str, FunctionNode]
    classes: dict[str, ast.ClassDef]
    bindings: _Bindings
    runner: str


@dataclass(eq=False)
class _Class:
    """A class and the module that defines it."""

    module: _Module
    node: ast.ClassDef


def _runner(path: str) -> str:
    """Return the test runner that collects ``path``'s tests."""
    return UNITTEST if path.startswith(UNITTEST_DIRECTORIES) else PYTEST


def _parse_module(path: str, text: str) -> _Module:
    """Parse ``text`` as module ``path``; raise SyntaxError if it doesn't parse."""
    tree = ast.parse(text.removeprefix("﻿"), filename=path)
    functions: dict[str, FunctionNode] = {}
    classes: dict[str, ast.ClassDef] = {}
    bindings = _Bindings()
    for node in _module_statements(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
        elif isinstance(node, ast.ClassDef):
            classes[node.name] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bindings.add(path, node)
    return _Module(path, tree, functions, classes, bindings, _runner(path))


def _is_direct_check(node: ast.AST, scopes: tuple[_Bindings, ...]) -> bool:
    """Whether ``node`` is itself a check, without following any helper."""
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Raise):
        return _raises_assertion_error(node)
    if not isinstance(node, ast.Call):
        return False
    name = _called_name(node)
    function = node.func
    owner = (
        function.value.id
        if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name)
        else None
    )
    return name is not None and (
        name.startswith(ASSERT_PREFIXES)
        or (owner == "self" and name == "fail")
        or any(
            (owner in scope.pytest_modules and name in PYTEST_CHECKS)
            or (
                isinstance(function, ast.Name)
                and (name in scope.pytest_names or name in scope.assert_names)
            )
            for scope in scopes
        )
    )


def _parameters(function: FunctionNode | ast.Lambda) -> set[str]:
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
class _Body:
    """What runs in a function's body, and the names it binds locally."""

    nodes: list[ast.AST]
    nested: frozenset[str]
    local_names: frozenset[str]
    bindings: _Bindings
    stand_in_calls: frozenset[int]


class _BodyReader:
    """Collect the nodes of a function's body that run when the test does.

    Decorators and default arguments are left out. A function, class or
    lambda assigned to a name inside the body counts only when the body refers
    to it by name, as a stand-in the code calls does; a used stand-in class
    counts with every method in it.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.nested: dict[str, list[ast.AST]] = {}
        self.nodes: list[ast.AST] = []
        self.loaded: set[str] = set()
        self.stored: set[str] = set()
        self.stand_in_calls: set[int] = set()

    def _defines(self, node: ast.AST) -> str | None:
        """Return the name a nested definition binds, if ``node`` is one."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return node.name
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Lambda)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            return node.targets[0].id
        return None

    def visit(self, statements: Iterable[ast.AST], *, stand_in: bool) -> None:
        stack = list(statements)
        while stack:
            current = stack.pop()
            name = self._defines(current)
            if name is not None:
                definition = (
                    current.value if isinstance(current, ast.Assign) else current
                )
                self.nested.setdefault(name, []).append(definition)
                continue
            self.nodes.append(current)
            if stand_in and isinstance(current, ast.Call):
                self.stand_in_calls.add(id(current))
            if isinstance(current, ast.Name):
                (self.loaded if isinstance(current.ctx, ast.Load) else self.stored).add(
                    current.id
                )
            elif isinstance(current, ast.ExceptHandler) and current.name:
                self.stored.add(current.name)
            stack.extend(ast.iter_child_nodes(current))

    def read(self, function: FunctionNode) -> _Body:
        self.visit(function.body, stand_in=False)
        parameters = _parameters(function)
        used: set[str] = set()
        while unused := (self.loaded & set(self.nested)) - used:
            for name in sorted(unused):
                used.add(name)
                for definition in self.nested[name]:
                    self._visit_definition(definition, parameters)
        bindings = _Bindings()
        for node in self.nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bindings.add(self.path, node)
        local_names = (self.stored | parameters) - bindings.bound_names()
        return _Body(
            self.nodes,
            frozenset(self.nested),
            frozenset(local_names),
            bindings,
            frozenset(self.stand_in_calls),
        )

    def _visit_definition(self, definition: ast.AST, parameters: set[str]) -> None:
        if isinstance(definition, ast.ClassDef):
            for statement in definition.body:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    parameters |= _parameters(statement)
                    self.visit(statement.body, stand_in=True)
                else:
                    self.visit([statement], stand_in=True)
        elif isinstance(definition, ast.Lambda):
            parameters |= _parameters(definition)
            self.visit([definition.body], stand_in=False)
        elif isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parameters |= _parameters(definition)
            self.visit(definition.body, stand_in=False)


@dataclass
class _Search:
    """State of one depth-first search for checks through helpers."""

    depth: dict[tuple[object, ...], int] = field(default_factory=dict)
    # Helpers that finished with False while a cycle above them is unresolved,
    # in finishing order, with their depth; and the lowest depth each reached.
    pending: list[tuple[tuple[object, ...], int]] = field(default_factory=list)
    pending_lowest: dict[tuple[object, ...], int] = field(default_factory=dict)
    lowest: int = 0

    def settle(
        self, depth: int, results: dict[tuple[object, ...], bool], *, value: bool | None
    ) -> None:
        """Settle the pending helpers deeper than ``depth``; store ``value`` if any."""
        while self.pending and self.pending[-1][1] > depth:
            key, _ = self.pending.pop()
            del self.pending_lowest[key]
            if value is not None:
                results[key] = value


class CheckIndex:
    """Which tests and helpers check something, across the repository's modules."""

    def __init__(self, root: Path) -> None:
        """Index modules under ``root``, reading each one only when needed."""
        self.root = root
        self._modules: dict[str, _Module | None] = {}
        self._results: dict[tuple[object, ...], bool] = {}
        self._search = _Search()

    def _read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8", errors="replace")

    def _test_module(self, path: str, text: str | None) -> _Module:
        """Parse the test module itself; raise SyntaxError if it doesn't parse."""
        module = _parse_module(path, self._read(path) if text is None else text)
        self._modules[path] = module
        return module

    def _test_code_module(self, stem: str) -> _Module | None:
        """Return the test-code module at path stem ``stem``, if it parses."""
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if not ((self.root / candidate).is_file() and _is_test_code(candidate)):
                continue
            if candidate not in self._modules:
                try:
                    self._modules[candidate] = _parse_module(
                        candidate, self._read(candidate)
                    )
                except (SyntaxError, ValueError):
                    self._modules[candidate] = None
            return self._modules[candidate]
        return None

    def _resolve(
        self, bindings: _Bindings, name: str, depth: int = 0
    ) -> tuple[_Module, str] | None:
        """Resolve an imported name to the test-code module that defines it.

        Re-exports and star imports are followed a few modules deep.
        """
        if depth > MAX_REEXPORT_DEPTH:
            return None
        sources = []
        if name in bindings.imports:
            sources.append(bindings.imports[name])
        else:
            sources.extend((stem, name) for stem in bindings.star_sources)
        for stem, original in sources:
            target = self._test_code_module(stem)
            if target is None:
                continue
            if original in target.functions or original in target.classes:
                return target, original
            found = self._resolve(target.bindings, original, depth + 1)
            if found is not None:
                return found
        return None

    def _module_named(self, module: _Module, name: str) -> _Module | None:
        """Return the test-code module a name in ``module`` refers to, if any."""
        if name in module.bindings.modules:
            return self._test_code_module(module.bindings.modules[name])
        if name in module.bindings.imports:
            stem, original = module.bindings.imports[name]
            return self._test_code_module(f"{stem}/{original}")
        return None

    def _class_named(self, module: _Module, expression: ast.expr) -> _Class | None:
        """Resolve a base-class expression to a class in test code, if it can."""
        if isinstance(expression, ast.Name):
            if expression.id in module.classes:
                return _Class(module, module.classes[expression.id])
            found = self._resolve(module.bindings, expression.id)
            if found is not None and found[1] in found[0].classes:
                return _Class(found[0], found[0].classes[found[1]])
        elif isinstance(expression, ast.Attribute) and isinstance(
            expression.value, ast.Name
        ):
            target = self._module_named(module, expression.value.id)
            if target is not None and expression.attr in target.classes:
                return _Class(target, target.classes[expression.attr])
        return None

    def _ancestry(self, cls: _Class) -> list[_Class]:
        """Return ``cls`` and every base that resolves, nearest first."""
        found: list[_Class] = []
        seen: set[tuple[str, int]] = set()
        pending = [cls]
        while pending:
            current = pending.pop(0)
            key = (current.module.path, current.node.lineno)
            if key in seen:
                continue
            seen.add(key)
            found.append(current)
            for base in current.node.bases:
                resolved = self._class_named(current.module, base)
                if resolved is not None:
                    pending.append(resolved)
        return found

    def _collection(self, cls: _Class, runner: str) -> str | None:
        """Return how ``runner`` collects ``cls``: unittest, pytest, or None."""
        ancestry = self._ancestry(cls)
        is_test_case = any(
            (
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
            ).endswith("TestCase")
            for member in ancestry
            for base in member.node.bases
        )
        if runner == UNITTEST:
            # unittest discover collects TestCase subclasses and ignores __test__.
            return UNITTEST if is_test_case else None
        switches = [_dunder_test(member.node.body) for member in ancestry]
        if next((switch for switch in switches if switch is not None), True) is False:
            return None
        if is_test_case:
            return UNITTEST
        if cls.node.name.startswith("Test") and not any(
            _defines_constructor(member.node) for member in ancestry
        ):
            return PYTEST
        return None

    def _class_tests(
        self,
        cls: _Class,
        prefix: str,
        collection: str,
        runner: str,
        name: str | None = None,
    ) -> Iterator[tuple[str, _Module, FunctionNode, _Class]]:
        qualified = f"{prefix}{name or cls.node.name}{SEPARATOR}"
        ancestry = self._ancestry(cls)
        seen: set[str] = set()
        for member in ancestry:
            for node in _module_statements(member.node.body):
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test")
                    and node.name not in seen
                    and "fixture" not in _decorator_names(node)
                ):
                    seen.add(node.name)
                    yield f"{qualified}{node.name}", member.module, node, cls
        if collection != PYTEST:
            return
        seen_classes: set[str] = set()
        for member in ancestry:
            for node in _module_statements(member.node.body):
                if isinstance(node, ast.ClassDef) and node.name not in seen_classes:
                    seen_classes.add(node.name)
                    nested = _Class(member.module, node)
                    nested_collection = self._collection(nested, runner)
                    if nested_collection is not None:
                        yield from self._class_tests(
                            nested, qualified, nested_collection, runner
                        )

    def _collected_tests(
        self, module: _Module
    ) -> Iterator[tuple[str, _Module, FunctionNode, _Class | None]]:
        """Yield each test the module's runner would collect from ``module``."""
        runner = module.runner
        if runner == PYTEST and _dunder_test(module.tree.body) is False:
            return
        for node in _module_statements(module.tree.body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    runner == PYTEST
                    and node.name.startswith("test")
                    and module.functions.get(node.name) is node
                    and "fixture" not in _decorator_names(node)
                ):
                    yield node.name, module, node, None
            elif (
                isinstance(node, ast.ClassDef) and module.classes.get(node.name) is node
            ):
                yield from self._tests_of_class(_Class(module, node), runner)
            elif isinstance(node, ast.ImportFrom):
                yield from self._imported_tests(module, node, runner)

    def _tests_of_class(
        self, cls: _Class, runner: str, name: str | None = None
    ) -> Iterator[tuple[str, _Module, FunctionNode, _Class | None]]:
        collection = self._collection(cls, runner)
        if collection is not None:
            yield from self._class_tests(cls, "", collection, runner, name)

    def _imported_tests(
        self, module: _Module, node: ast.ImportFrom, runner: str
    ) -> Iterator[tuple[str, _Module, FunctionNode, _Class | None]]:
        """Yield the tests a test module imports by name, which pytest also runs."""
        for alias in node.names:
            bound = alias.asname or alias.name
            if bound in module.functions or bound in module.classes:
                continue
            found = self._resolve(module.bindings, bound)
            if found is None:
                continue
            target, original = found
            if original in target.classes:
                yield from self._tests_of_class(
                    _Class(target, target.classes[original]), runner, bound
                )
            elif (
                runner == PYTEST
                and bound.startswith("test")
                and "fixture" not in _decorator_names(target.functions[original])
            ):
                yield bound, target, target.functions[original], None

    def _method(
        self, owner: _Class, name: str, skip: FunctionNode | None = None
    ) -> tuple[_Module, FunctionNode] | None:
        """Find method ``name`` on ``owner``; with ``skip``, only above its class."""
        searching = skip is None
        for member in self._ancestry(owner):
            if not searching:
                searching = skip in member.node.body
                continue
            for node in member.node.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == name
                ):
                    return member.module, node
        return None

    def _helper(
        self,
        module: _Module,
        function: FunctionNode,
        owner: _Class | None,
        body: _Body,
        call: ast.Call,
    ) -> tuple[_Module, FunctionNode, _Class | None] | None:
        """Return the helper ``call`` calls, if the guard can tell which it is."""
        called = call.func
        if isinstance(called, ast.Name):
            return self._named_helper(module, body, called.id)
        if not isinstance(called, ast.Attribute) or owner is None:
            return None
        if id(call) in body.stand_in_calls:
            return None
        receiver = called.value
        if isinstance(receiver, ast.Name) and receiver.id in {"self", "cls"}:
            method = self._method(owner, called.attr)
        elif (
            isinstance(receiver, ast.Call)
            and isinstance(receiver.func, ast.Name)
            and receiver.func.id == "super"
        ):
            method = self._method(owner, called.attr, skip=function)
        else:
            return None
        return None if method is None else (method[0], method[1], owner)

    def _named_helper(
        self, module: _Module, body: _Body, name: str
    ) -> tuple[_Module, FunctionNode, _Class | None] | None:
        if name in body.nested:
            return None
        for bindings in (body.bindings, module.bindings):
            if bindings is module.bindings:
                if name in body.local_names:
                    return None
                if name in module.functions:
                    return module, module.functions[name], None
            found = self._resolve(bindings, name)
            if found is not None and found[1] in found[0].functions:
                return found[0], found[0].functions[found[1]], None
        return None

    def _checks(
        self, module: _Module, function: FunctionNode, owner: _Class | None
    ) -> bool:
        """Whether ``function`` checks something, directly or through a helper.

        A depth-first search: a helper reached again while it is still being
        evaluated counts as checking nothing for now, and a result that rested
        on that is stored only once the helper that started the cycle is done.
        """
        owner_key = None if owner is None else (owner.module.path, owner.node.lineno)
        key = (module.path, function.lineno, function.col_offset, owner_key)
        if key in self._results:
            return self._results[key]
        search = self._search
        if key in search.depth or key in search.pending_lowest:
            reached = search.depth.get(key, search.pending_lowest.get(key, 0))
            search.lowest = min(search.lowest, reached)
            return False
        depth = len(search.depth)
        search.depth[key] = depth
        outer_lowest, search.lowest = search.lowest, depth
        try:
            body = _BodyReader(module.path).read(function)
            scopes = (body.bindings, module.bindings)
            result = any(_is_direct_check(node, scopes) for node in body.nodes) or any(
                (helper := self._helper(module, function, owner, body, node))
                is not None
                and self._checks(*helper)
                for node in body.nodes
                if isinstance(node, ast.Call)
            )
        finally:
            del search.depth[key]
        lowest = search.lowest
        if result:
            # Pending helpers below may reach this one, so they are evaluated
            # again later, against the stored True.
            self._results[key] = True
            search.settle(depth, self._results, value=None)
        elif lowest >= depth:
            # This helper started every cycle below it, and nothing it reaches
            # checks anything.
            self._results[key] = False
            search.settle(depth, self._results, value=False)
        else:
            search.pending.append((key, depth))
            search.pending_lowest[key] = lowest
        search.lowest = min(outer_lowest, lowest)
        return result

    def unchecked_tests(
        self, path: str, text: str | None = None
    ) -> list[UncheckedTest]:
        """Return the tests in module ``path`` that check nothing.

        Read ``text`` as the module's source when given. Raise SyntaxError when
        the module doesn't parse.
        """
        module = self._test_module(path, text)
        unchecked = []
        for name, defining_module, function, owner in self._collected_tests(module):
            self._search = _Search()
            if not self._checks(defining_module, function, owner):
                line = (
                    function.lineno
                    if defining_module is module
                    else (owner.node.lineno if owner is not None else 1)
                )
                unchecked.append(UncheckedTest(path, line, name))
        return unchecked
