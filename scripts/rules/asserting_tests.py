"""The asserting-tests quality guard: every test function checks something.

A test that checks nothing passes whatever the code returns, as long as nothing
raises. The guard reads every tracked test file (``test_*.py`` or
``*_test.py``, outside fixture directories) with ``ast`` and fails on any
test function, as pytest and unittest collect them, that contains none of:

- an ``assert`` statement, or ``raise AssertionError``;
- ``pytest.raises``, ``pytest.warns``, ``pytest.deprecated_call`` or
  ``pytest.fail``, also when imported from pytest by name;
- a call to a function or method whose name starts with ``assert``, such as
  unittest's ``self.assertEqual``, a mock's ``assert_called_once_with`` or
  ``assert_frame_equal``, or unittest's ``self.fail``;
- a call to a helper that does one of these: a function defined in the same
  file, or imported by name from another module in the repository, followed
  through further helpers.

Nested functions count as part of the test, so a stand-in that raises
``AssertionError`` when it is called is a check.

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
from dataclasses import dataclass
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
FIXTURE_DIRECTORY = "fixtures"
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

    Files under a ``fixtures`` directory hold test data, not tests.
    """
    parts = PurePosixPath(path).parts
    name = parts[-1]
    return (
        name.endswith(".py")
        and (name.startswith("test_") or name.endswith("_test.py"))
        and FIXTURE_DIRECTORY not in parts[:-1]
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


def _is_checking_call(call: ast.Call, pytest_names: frozenset[str]) -> bool:
    """Whether a call is a check: an assert function, pytest's, or ``self.fail``."""
    name = _called_name(call)
    if name is None:
        return False
    function = call.func
    owner = (
        function.value.id
        if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name)
        else None
    )
    return (
        name.startswith(("assert", "_assert"))
        or (owner == "pytest" and name in PYTEST_CHECKS)
        or (owner == "self" and name == "fail")
        or (isinstance(function, ast.Name) and name in pytest_names)
    )


def _is_direct_check(node: ast.AST, pytest_names: frozenset[str]) -> bool:
    """Whether ``node`` is itself a check, without following any helper."""
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Raise):
        return _raises_assertion_error(node)
    return isinstance(node, ast.Call) and _is_checking_call(node, pytest_names)


@dataclass
class _Module:
    """What the guard needs from one parsed module."""

    tree: ast.Module
    functions: dict[str, list[FunctionNode]]
    imported_functions: dict[str, tuple[str, str]]
    pytest_names: frozenset[str]


def _module_path(importer: str, module: str | None, level: int) -> str | None:
    """Return the repository path stem ``a/b/c`` an import names, if it can tell."""
    if level == 0:
        return module.replace(".", "/") if module else None
    package = PurePosixPath(importer).parent
    for _ in range(level - 1):
        package = package.parent
    stem = package.as_posix() if package.as_posix() != "." else ""
    if module:
        stem = (
            f"{stem}/{module.replace('.', '/')}" if stem else module.replace(".", "/")
        )
    return stem or None


def _parse_module(path: str, tree: ast.Module) -> _Module:
    functions: dict[str, list[FunctionNode]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.setdefault(node.name, []).append(node)
    imported: dict[str, tuple[str, str]] = {}
    pytest_names = set()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == "pytest" and node.level == 0:
            pytest_names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in PYTEST_CHECKS
            )
            continue
        stem = _module_path(path, node.module, node.level)
        if stem is None:
            continue
        for alias in node.names:
            imported[alias.asname or alias.name] = (stem, alias.name)
    return _Module(tree, functions, imported, frozenset(pytest_names))


class CheckIndex:
    """Which functions check something, across the repository's modules."""

    def __init__(self, root: Path) -> None:
        """Index modules under ``root``, reading each one only when needed."""
        self.root = root
        self._modules: dict[str, _Module | None] = {}
        self._checking: dict[tuple[str, str], bool] = {}

    def _module(self, path: str, text: str | None = None) -> _Module | None:
        if path not in self._modules:
            if text is None:
                file = self.root / path
                if not file.is_file():
                    self._modules[path] = None
                    return None
                text = file.read_text(encoding="utf-8", errors="replace")
            self._modules[path] = _parse_module(path, ast.parse(text, filename=path))
        return self._modules[path]

    def _resolve(self, stem: str) -> str | None:
        """Return the tracked file for module path ``stem``, if there is one."""
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if (self.root / candidate).is_file():
                return candidate
        return None

    def _function_checks(self, path: str, name: str) -> bool:
        """Whether a function ``name`` in module ``path`` checks something."""
        key = (path, name)
        if key in self._checking:
            return self._checking[key]
        # A helper that calls itself, directly or through others, is assumed not
        # to check anything until one of its calls is shown to.
        self._checking[key] = False
        module = self._module(path)
        result = False
        if module is not None:
            if name in module.functions:
                result = any(
                    self._body_checks(path, module, function)
                    for function in module.functions[name]
                )
            elif name in module.imported_functions:
                stem, original = module.imported_functions[name]
                target = self._resolve(stem)
                result = target is not None and self._function_checks(target, original)
        self._checking[key] = result
        return result

    def _body_checks(self, path: str, module: _Module, function: FunctionNode) -> bool:
        for node in ast.walk(function):
            if _is_direct_check(node, module.pytest_names):
                return True
            if isinstance(node, ast.Call) and self._calls_checking_helper(
                path, module, node, function.name
            ):
                return True
        return False

    def _calls_checking_helper(
        self, path: str, module: _Module, call: ast.Call, caller: str
    ) -> bool:
        """Whether ``call`` calls a helper, other than ``caller``, that checks."""
        name = _called_name(call)
        known = name in module.functions or name in module.imported_functions
        return (
            name is not None
            and name != caller
            and known
            and self._function_checks(path, name)
        )

    def unchecked_tests(
        self, path: str, text: str | None = None
    ) -> list[UncheckedTest]:
        """Return the tests in module ``path`` that check nothing.

        Read ``text`` as the module's source when given. Raise SyntaxError when
        the module doesn't parse.
        """
        module = self._module(path, text)
        if module is None:
            return []
        return [
            UncheckedTest(path, function.lineno, name)
            for name, function in _collected_tests(module.tree.body, "")
            if not self._body_checks(path, module, function)
        ]


def _is_test_class(node: ast.ClassDef) -> bool:
    """Whether pytest collects tests from the class: ``Test*`` or a TestCase."""
    return node.name.startswith("Test") or any(
        (isinstance(base, ast.Name) and base.id.endswith("TestCase"))
        or (isinstance(base, ast.Attribute) and base.attr.endswith("TestCase"))
        for base in node.bases
    )


def _collected_tests(
    body: Iterable[ast.stmt], prefix: str
) -> Iterator[tuple[str, FunctionNode]]:
    """Yield ``(qualified name, function)`` for each test pytest would collect."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                yield f"{prefix}{node.name}", node
        elif isinstance(node, ast.ClassDef) and _is_test_class(node):
            yield from _collected_tests(node.body, f"{prefix}{node.name}{SEPARATOR}")


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
        except SyntaxError:
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
