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
  own class called through ``self``, ``cls`` or ``super()``, or a function
  imported by name (at module level or in the test, also through a re-export
  or a star import) from test code: a module under a ``tests`` directory, a
  test file or a ``conftest.py``. Production code isn't a helper, and neither
  is a name the test binds itself, such as a fixture parameter.

Only the test's body counts, not its decorators or default arguments. A
function, class or lambda assigned to a name in the body counts only when the
body refers to it by name, as a stand-in the code calls does; ``self`` in a
stand-in class's methods is the stand-in, not the test's class.

Collection follows pytest for what the guard can read without importing:
module-level ``test*`` functions, also in ``if``, ``try`` and ``with`` blocks,
except fixtures; ``test*`` methods of ``Test*`` classes that have no
``__init__`` or ``__new__`` and aren't dataclasses, including methods and
nested ``Test*`` classes inherited from bases in test code; ``TestCase``
subclasses; and test functions and classes imported by name into the test
module. The nearest ``__test__`` setting on a module or class decides whether
it is collected. Files under ``check_index.UNITTEST_DIRECTORIES`` run under
``unittest discover``, which collects only ``TestCase`` subclasses and ignores
``__test__``. A base class outside test code isn't read, so an ``__init__``
there isn't seen. The analysis is in scripts/rules/check_index.py.

While the rule is ratcheted, its baseline file lists the tolerated tests, one
``<path>::<test>`` per line (``<test>`` is ``Class::method`` for a method). A
test the baseline doesn't list fails, and so does a listed one that is gone or
now checks something, so the baseline only shrinks.

The rule: docs/engineering/skills/testing.md#every-test-checks-something.
Standard library only.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.rules.check_index import CheckIndex, UncheckedTest, is_test_file
from scripts.rules.load import load_registry
from scripts.rules.model import Violation

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
RULE_ID = "api.quality.tests-assert"
CHECK_NAME = "asserting-tests"
# CheckIndex, UncheckedTest and is_test_file live in scripts/rules/check_index.py
# and are part of this module's public interface.
__all__ = [
    "CHECK_NAME",
    "REPO_ROOT",
    "RULE_ID",
    "CheckIndex",
    "UncheckedTest",
    "check",
    "compare",
    "is_test_file",
    "run_check",
]
FIX = (
    "check its outcome: assert on what the code returns or changes, use "
    "pytest.raises for an expected error, or call a helper that asserts; a test "
    "that only shows that nothing raises can assert what the call returns "
    "(docs/engineering/skills/testing.md#every-test-checks-something)"
)


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
