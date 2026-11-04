"""The asserting-tests quality guard: every test function checks something.

A test that checks nothing passes whatever the code returns, as long as nothing
raises. The guard reads every tracked test file (``test_*.py`` or
``*_test.py``, apart from the rules' proof fixtures) with ``ast``, finds the
tests pytest and unittest collect from it, and fails on any test that
contains none of:

- an ``assert`` statement, or ``raise AssertionError``;
- ``pytest.raises``, ``pytest.warns``, ``pytest.deprecated_call`` or
  ``pytest.fail``, also through ``import pytest as ...`` or a by-name import;
- a call to a function or method whose name starts with ``assert`` or
  ``_assert``, such as unittest's ``self.assertEqual``, a mock's
  ``assert_called_once_with`` or ``assert_frame_equal``, also when imported
  under another name, or unittest's ``self.fail``;
- a call to a helper that does one of these, followed through further
  helpers: a function of the same file called by name, a method of the test's
  own class called through ``self`` or ``cls``, or a function imported by name
  from test code (a module under a ``tests`` directory, a test file or a
  ``conftest.py``). Production code isn't a helper.

Only the test's body counts, not its decorators or default arguments. A
function or class defined in the body counts only when the body refers to it
by name, as a stand-in the code calls does.

Collection follows pytest: module-level ``test*`` functions, also in ``if``,
``try`` and ``with`` blocks; ``test*`` methods of ``Test*`` classes without an
``__init__``, including inherited ones and nested ``Test*`` classes; and
``unittest.TestCase`` subclasses, also through a base the guard can resolve.
``__test__ = False`` on a module or class switches collection off.

While the rule is ratcheted, its baseline file lists the tolerated tests, one
``<path>::<test>`` per line (``<test>`` is ``Class::method`` for a method). A
test the baseline doesn't list fails, and so does a listed one that is gone or
now checks something, so the baseline only shrinks.

The rule: docs/engineering/skills/testing.md#every-test-checks-something.
Standard library only.
"""

from __future__ import annotations

import ast
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from scripts.rules.load import load_registry
from scripts.rules.model import Violation

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
RULE_ID = "api.quality.tests-assert"
CHECK_NAME = "asserting-tests"
SEPARATOR = "::"
PYTEST_CHECKS = frozenset({"raises", "warns", "deprecated_call", "fail"})
ASSERT_PREFIXES = ("assert", "_assert")
# Proof fixtures for the rules: test data that no test runner collects.
EXCLUDED_PREFIXES = ("rules/fixtures/", "scripts/rules/tests/fixtures/")
TEST_DIRECTORY = "tests"
PYTEST = "pytest"
UNITTEST = "unittest"
FIX = (
    "check its outcome: assert on what the code returns or changes, use "
    "pytest.raises for an expected error, or call a helper that asserts; a test "
    "that only shows that nothing raises can assert what the call returns "
    "(docs/engineering/skills/testing.md#every-test-checks-something)"
)

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
    """Yield a module's statements, including those in if, try and with blocks."""
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


def _switched_off(body: Iterable[ast.stmt]) -> bool:
    """Whether a module or class body sets ``__test__ = False``."""
    return any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__test__"
            for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
        and node.value.value is False
        for node in body
    )


def _defines_init(node: ast.ClassDef) -> bool:
    return any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == "__init__"
        for statement in node.body
    )


@dataclass(eq=False)
class _Module:
    """What the guard needs from one parsed module."""

    path: str
    tree: ast.Module
    functions: dict[str, FunctionNode]
    classes: dict[str, ast.ClassDef]
    imports: dict[str, tuple[str, str]]
    pytest_modules: frozenset[str]
    pytest_names: frozenset[str]
    assert_names: frozenset[str]


@dataclass(eq=False)
class _Class:
    """A class and the module that defines it."""

    module: _Module
    node: ast.ClassDef


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
class _ImportBindings:
    """The names a module's imports bind, as the guard reads them."""

    imports: dict[str, tuple[str, str]] = field(default_factory=dict)
    pytest_modules: set[str] = field(default_factory=lambda: {"pytest"})
    pytest_names: set[str] = field(default_factory=set)
    assert_names: set[str] = field(default_factory=set)

    def add_from_import(self, path: str, node: ast.ImportFrom) -> None:
        """Record what ``from module import name`` binds in module ``path``."""
        for alias in node.names:
            bound = alias.asname or alias.name
            if alias.name.startswith(ASSERT_PREFIXES):
                self.assert_names.add(bound)
            if node.module == "pytest" and node.level == 0:
                if alias.name in PYTEST_CHECKS:
                    self.pytest_names.add(bound)
                continue
            stem = _module_path(path, node.module, node.level)
            if stem is not None:
                self.imports[bound] = (stem, alias.name)


def _parse_module(path: str, text: str) -> _Module:
    """Parse ``text`` as module ``path``; raise SyntaxError if it doesn't parse."""
    tree = ast.parse(text.removeprefix("﻿"), filename=path)
    functions: dict[str, FunctionNode] = {}
    classes: dict[str, ast.ClassDef] = {}
    for node in _module_statements(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
        elif isinstance(node, ast.ClassDef):
            classes[node.name] = node
    bindings = _ImportBindings()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bindings.pytest_modules.update(
                alias.asname
                for alias in node.names
                if alias.name == "pytest" and alias.asname
            )
        elif isinstance(node, ast.ImportFrom):
            bindings.add_from_import(path, node)
    return _Module(
        path,
        tree,
        functions,
        classes,
        bindings.imports,
        frozenset(bindings.pytest_modules),
        frozenset(bindings.pytest_names),
        frozenset(bindings.assert_names),
    )


def _is_direct_check(node: ast.AST, module: _Module) -> bool:
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
        or (owner in module.pytest_modules and name in PYTEST_CHECKS)
        or (owner == "self" and name == "fail")
        or (
            isinstance(function, ast.Name)
            and (name in module.pytest_names or name in module.assert_names)
        )
    )


def _body_nodes(function: FunctionNode) -> tuple[list[ast.AST], frozenset[str]]:
    """Return the nodes of a function's body that run, and its nested names.

    Decorators and default arguments are left out. A function or class defined
    inside the body counts only when the body refers to it by name, as a
    stand-in the code calls does; a used stand-in class counts with every
    method in it.
    """
    nested: dict[str, list[FunctionNode | ast.ClassDef]] = {}
    included: list[ast.AST] = []
    loaded: set[str] = set()

    def visit(statements: Iterable[ast.AST]) -> None:
        stack = list(statements)
        while stack:
            current = stack.pop()
            if isinstance(
                current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                nested.setdefault(current.name, []).append(current)
                continue
            included.append(current)
            if isinstance(current, ast.Name) and isinstance(current.ctx, ast.Load):
                loaded.add(current.id)
            stack.extend(ast.iter_child_nodes(current))

    visit(function.body)
    used: set[str] = set()
    while unused := (loaded & set(nested)) - used:
        for name in sorted(unused):
            used.add(name)
            for definition in nested[name]:
                visit(_definition_body(definition))
    return included, frozenset(nested)


def _definition_body(definition: FunctionNode | ast.ClassDef) -> list[ast.AST]:
    """Return what runs of a nested function, or of every method of a class."""
    if not isinstance(definition, ast.ClassDef):
        return list(definition.body)
    body: list[ast.AST] = []
    for statement in definition.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body.extend(statement.body)
        else:
            body.append(statement)
    return body


class CheckIndex:
    """Which tests and helpers check something, across the repository's modules."""

    def __init__(self, root: Path) -> None:
        """Index modules under ``root``, reading each one only when needed."""
        self.root = root
        self._modules: dict[str, _Module | None] = {}
        self._results: dict[tuple[object, ...], bool] = {}
        self._in_progress: set[tuple[object, ...]] = set()
        self._reached_cycle = False

    def _read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8", errors="replace")

    def _test_module(self, path: str, text: str | None) -> _Module:
        """Parse the test module itself; raise SyntaxError if it doesn't parse."""
        module = _parse_module(path, self._read(path) if text is None else text)
        self._modules[path] = module
        return module

    def _helper_module(self, path: str) -> _Module | None:
        """Parse a module a test imports from, or None if it doesn't parse."""
        if path not in self._modules:
            try:
                self._modules[path] = _parse_module(path, self._read(path))
            except (SyntaxError, ValueError):
                self._modules[path] = None
        return self._modules[path]

    def _imported(self, module: _Module, name: str) -> tuple[_Module, str] | None:
        """Resolve a by-name import to the test-code module and name it binds."""
        if name not in module.imports:
            return None
        stem, original = module.imports[name]
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if (self.root / candidate).is_file() and _is_test_code(candidate):
                target = self._helper_module(candidate)
                return None if target is None else (target, original)
        return None

    def _base_classes(self, cls: _Class) -> list[_Class]:
        """Return the bases of ``cls`` that resolve to classes in test code."""
        bases = []
        for base in cls.node.bases:
            if not isinstance(base, ast.Name):
                continue
            if base.id in cls.module.classes:
                bases.append(_Class(cls.module, cls.module.classes[base.id]))
                continue
            imported = self._imported(cls.module, base.id)
            if imported is not None and imported[1] in imported[0].classes:
                bases.append(_Class(imported[0], imported[0].classes[imported[1]]))
        return bases

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
            pending.extend(self._base_classes(current))
        return found

    def _collection(self, cls: _Class) -> str | None:
        """Return how a test runner collects ``cls``: unittest, pytest, or None."""
        ancestry = self._ancestry(cls)
        if any(_switched_off(member.node.body) for member in ancestry):
            return None
        for member in ancestry:
            for base in member.node.bases:
                name = (
                    base.id
                    if isinstance(base, ast.Name)
                    else base.attr
                    if isinstance(base, ast.Attribute)
                    else ""
                )
                if name.endswith("TestCase"):
                    return UNITTEST
        if cls.node.name.startswith("Test") and not any(
            _defines_init(member.node) for member in ancestry
        ):
            return PYTEST
        return None

    def _class_tests(
        self, cls: _Class, prefix: str, collection: str
    ) -> Iterator[tuple[str, _Module, FunctionNode, _Class]]:
        qualified = f"{prefix}{cls.node.name}{SEPARATOR}"
        seen: set[str] = set()
        for member in self._ancestry(cls):
            for node in member.node.body:
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test")
                    and node.name not in seen
                ):
                    seen.add(node.name)
                    yield f"{qualified}{node.name}", member.module, node, cls
        if collection != PYTEST:
            return
        for node in cls.node.body:
            if isinstance(node, ast.ClassDef):
                nested = _Class(cls.module, node)
                nested_collection = self._collection(nested)
                if nested_collection is not None:
                    yield from self._class_tests(nested, qualified, nested_collection)

    def _collected_tests(
        self, module: _Module
    ) -> Iterator[tuple[str, _Module, FunctionNode, _Class | None]]:
        """Yield each test pytest or unittest would collect from ``module``."""
        if _switched_off(module.tree.body):
            return
        for node in _module_statements(module.tree.body):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    node.name.startswith("test")
                    and module.functions.get(node.name) is node
                ):
                    yield node.name, module, node, None
            elif (
                isinstance(node, ast.ClassDef) and module.classes.get(node.name) is node
            ):
                cls = _Class(module, node)
                collection = self._collection(cls)
                if collection is not None:
                    yield from self._class_tests(cls, "", collection)

    def _method(self, owner: _Class, name: str) -> tuple[_Module, FunctionNode] | None:
        for member in self._ancestry(owner):
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
        call: ast.Call,
        owner: _Class | None,
        nested: frozenset[str],
    ) -> tuple[_Module, FunctionNode, _Class | None] | None:
        """Return the helper ``call`` calls, if the guard can tell which it is."""
        function = call.func
        if isinstance(function, ast.Name):
            name = function.id
            if name in nested:
                return None
            if name in module.functions:
                return module, module.functions[name], None
            imported = self._imported(module, name)
            if imported is not None and imported[1] in imported[0].functions:
                return imported[0], imported[0].functions[imported[1]], None
            return None
        if (
            owner is not None
            and isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id in {"self", "cls"}
        ):
            method = self._method(owner, function.attr)
            if method is not None:
                return method[0], method[1], owner
        return None

    def _checks(
        self, module: _Module, function: FunctionNode, owner: _Class | None
    ) -> bool:
        """Whether ``function`` checks something, directly or through a helper."""
        owner_key = None if owner is None else (owner.module.path, owner.node.lineno)
        key = (module.path, function.lineno, function.col_offset, owner_key)
        if key in self._results:
            return self._results[key]
        if key in self._in_progress:
            # A helper reached again through its own calls: its result isn't
            # known yet, so nothing that depends on it is stored as False.
            self._reached_cycle = True
            return False
        outer_reached_cycle = self._reached_cycle
        self._reached_cycle = False
        self._in_progress.add(key)
        try:
            included, nested = _body_nodes(function)
            result = any(_is_direct_check(node, module) for node in included) or any(
                (helper := self._helper(module, node, owner, nested)) is not None
                and self._checks(*helper)
                for node in included
                if isinstance(node, ast.Call)
            )
        finally:
            self._in_progress.discard(key)
        if result or not self._reached_cycle:
            self._results[key] = result
        self._reached_cycle = self._reached_cycle or outer_reached_cycle
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
            self._reached_cycle = False
            if not self._checks(defining_module, function, owner):
                line = (
                    function.lineno
                    if defining_module is module or owner is None
                    else owner.node.lineno
                )
                unchecked.append(UncheckedTest(path, line, name))
        return unchecked


def _describe(test: UncheckedTest) -> str:
    return (
        f"{test.path}:{test.line}: {test.name} checks nothing: it has no assert, "
        "no pytest.raises and no other check"
    )


def compare(
    found: Iterable[UncheckedTest], baseline: Iterable[str], baseline_file: str | None
) -> list[Violation]:
    """Report tests the baseline doesn't list, and listed ones now gone or checked.

    Each baseline line tolerates one test with its entry.
    """
    found = list(found)
    allowed = Counter(baseline)
    present = Counter(test.entry for test in found)
    violations = []
    seen: Counter[str] = Counter()
    for test in found:
        seen[test.entry] += 1
        if seen[test.entry] > allowed[test.entry]:
            violations.append(Violation(RULE_ID, CHECK_NAME, _describe(test), FIX))
    for entry in sorted(allowed):
        violations.extend(
            Violation(
                RULE_ID,
                CHECK_NAME,
                f"baseline entry no longer applies: {entry}",
                f"remove it from {baseline_file} and lower the rule's baseline count",
            )
            for _ in range(allowed[entry] - present[entry])
        )
    return violations


def _tracked_test_files(root: Path) -> list[str]:
    """Return the tracked test files, or every one in a plain tree.

    A directory that isn't a git checkout (a test's temporary tree) has every
    test file under it read.
    """
    if (root / ".git").exists():
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split("\0")
        paths = [path for path in listed if path and (root / path).is_file()]
    else:
        paths = [path.relative_to(root).as_posix() for path in root.rglob("*.py")]
    return sorted(path for path in paths if is_test_file(path))


def _baseline_lines(root: Path, baseline_file: str | None) -> list[str]:
    """Read the baseline's entries, one per line, keeping repeated entries."""
    if baseline_file is None or not (root / baseline_file).is_file():
        return []
    return [
        line.strip()
        for line in (root / baseline_file).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def run_check(root: Path = REPO_ROOT) -> list[Violation]:
    """Load the rule from the registry under ``root`` and read every test file."""
    registry, violations = load_registry(root)
    if registry is None:
        return violations
    rule = registry.rule(RULE_ID)
    if rule is None:
        return [
            Violation(
                None,
                CHECK_NAME,
                f"rules/registry.toml has no rule {RULE_ID}",
                "register the rule",
            )
        ]
    index = CheckIndex(root)
    violations = []
    found = []
    for path in _tracked_test_files(root):
        try:
            found.extend(index.unchecked_tests(path))
        except (SyntaxError, ValueError):
            violations.append(
                Violation(
                    RULE_ID,
                    CHECK_NAME,
                    f"{path} doesn't parse, so its tests can't be checked",
                    "fix the syntax error (ruff check reports it)",
                )
            )
    baseline_file = rule.baseline.file if rule.baseline is not None else None
    return [
        *violations,
        *compare(found, _baseline_lines(root, baseline_file), baseline_file),
    ]


def check() -> list[str]:
    """Adapter for scripts/run_quality_guards.py."""
    return [str(violation) for violation in run_check(REPO_ROOT)]
