"""Tests for the asserting-tests guard: every test function checks something."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.rules.asserting_tests import (
    REPO_ROOT,
    RULE_ID,
    CheckIndex,
    UncheckedTest,
    compare,
    is_test_file,
    run_check,
)

FIXTURES = REPO_ROOT / "rules" / "fixtures" / RULE_ID
BASELINE_FILE = "rules/baselines/tests-without-checks.txt"


def _write(root: Path, relative_path: str, text: str) -> None:
    file = root / relative_path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(textwrap.dedent(text))


def _unchecked(root: Path, path: str, text: str) -> list[str]:
    return [test.name for test in CheckIndex(root).unchecked_tests(path, text)]


def _registry_with_rule(baseline_block: str) -> str:
    """Return a registry holding only the asserting-tests rule."""
    return textwrap.dedent(
        f"""
        schema_version = 1
        repo = "example"

        [[category]]
        id = "quality"
        title = "Quality"

        [[rule]]
        id = "{RULE_ID}"
        category = "quality"
        statement = "Tests check something."
        rationale = "docs/guide.md"
        scope = ["tests/**/*.py"]
        tier = "mechanical"
        status = "ratcheted"
        autofix = false
        [rule.enforcer]
        kind = "quality-guard"
        name = "asserting-tests"
        [[rule.ci]]
        workflow = ".github/workflows/pr.yml"
        job = "quality-guards"
        invocation = "run_quality_guards.py"
        {baseline_block}
        """
    )


class TestAssertingTestsProof(unittest.TestCase):
    """Proof: the rejected fixture's tests fail, the accepted fixture's pass."""

    def test_rule_proof_tests_assert(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rejected = _unchecked(
                root, "test_rejected.py", (FIXTURES / "rejected_tests.txt").read_text()
            )
            accepted = _unchecked(
                root, "test_accepted.py", (FIXTURES / "accepted_tests.txt").read_text()
            )
        self.assertEqual(
            rejected,
            [
                "test_calls_without_checking",
                "test_calls_a_helper_that_checks_nothing",
                "test_awaits_without_checking",
                "TestThing::test_method_without_check",
                "TestThing::TestNested::test_nested_without_check",
                "ThingCase::test_unittest_method_without_check",
            ],
        )
        self.assertEqual(accepted, [])


class TestTestFiles(unittest.TestCase):
    """Which files pytest and unittest collect tests from."""

    def test_test_file_names(self) -> None:
        for path, expected in (
            ("tests/unit/test_service.py", True),
            ("tests/unit/service_test.py", True),
            ("scripts/rules/tests/test_guard.py", True),
            ("tests/unit/support.py", False),
            ("tests/conftest.py", False),
            (
                "scripts/rules/tests/fixtures/ci_scripts/untested_good/tests/test_deploy.py",
                False,
            ),
            ("rules/fixtures/example/test_bad.py", False),
            ("policyengine_api/testing.py", False),
        ):
            with self.subTest(path=path):
                self.assertEqual(is_test_file(path), expected)


class TestImportedHelpers(unittest.TestCase):
    """A helper imported by name from another repository module is followed."""

    def test_an_imported_checking_helper_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(
                root,
                "tests/support.py",
                """
                from tests.more_support import check_deeper


                def check_response(response):
                    assert response.ok


                def check_through_another_module(response):
                    check_deeper(response)


                def build_response():
                    return object()
                """,
            )
            _write(
                root,
                "tests/more_support.py",
                """
                def check_deeper(response):
                    assert response
                """,
            )
            source = textwrap.dedent(
                """
                from tests.support import (
                    build_response,
                    check_response,
                    check_through_another_module as check_twice,
                )
                from .support import check_response as relative_check


                def test_imported_helper():
                    check_response(build_response())


                def test_helper_from_a_third_module():
                    check_twice(build_response())


                def test_relative_import():
                    relative_check(build_response())


                def test_imported_helper_that_checks_nothing():
                    build_response()
                """
            )
            unchecked = _unchecked(root, "tests/test_responses.py", source)
        self.assertEqual(unchecked, ["test_imported_helper_that_checks_nothing"])

    def test_a_helper_that_calls_itself_ends(self) -> None:
        source = textwrap.dedent(
            """
            def first(value):
                return second(value)


            def second(value):
                return first(value)


            def test_loops():
                first(1)
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                _unchecked(Path(directory), "test_loops.py", source), ["test_loops"]
            )


class TestBaseline(unittest.TestCase):
    """The baseline tolerates listed tests and may only shrink."""

    def test_unlisted_test_fails(self) -> None:
        found = [
            UncheckedTest("tests/test_a.py", 3, "test_listed"),
            UncheckedTest("tests/test_a.py", 9, "TestThing::test_new"),
        ]
        violations = compare(found, ["tests/test_a.py::test_listed"], BASELINE_FILE)
        self.assertEqual(
            [str(violation) for violation in violations],
            [
                f"[{RULE_ID}] asserting-tests: tests/test_a.py:9: "
                "TestThing::test_new checks nothing: it has no assert, no "
                "pytest.raises and no other check. Fix: check its outcome: assert "
                "on what the code returns or changes, use pytest.raises for an "
                "expected error, or call a helper that asserts; a test that only "
                "shows that nothing raises can assert what the call returns "
                "(docs/engineering/skills/testing.md#every-test-checks-something)."
            ],
        )

    def test_listed_entry_no_longer_found_fails(self) -> None:
        violations = compare([], ["tests/test_a.py::test_gone"], BASELINE_FILE)
        self.assertEqual(
            [violation.message for violation in violations],
            ["baseline entry no longer applies: tests/test_a.py::test_gone"],
        )


class TestRunCheck(unittest.TestCase):
    """The guard reads every test file under the root against the baseline."""

    def test_scans_test_files_and_reads_the_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(
                root,
                BASELINE_FILE,
                "# Tolerated.\ntests/test_old.py::test_old\n",
            )
            _write(
                root,
                "rules/registry.toml",
                _registry_with_rule(
                    f'[rule.baseline]\nfile = "{BASELINE_FILE}"\ncount = 1\n'
                ),
            )
            _write(root, "tests/test_old.py", "def test_old():\n    pass\n")
            _write(root, "tests/test_new.py", "def test_new():\n    pass\n")
            _write(root, "tests/support.py", "def test_like_helper():\n    pass\n")
            _write(root, "tests/test_broken.py", "def test_broken(:\n")
            messages = [violation.message for violation in run_check(root)]
        self.assertEqual(
            messages,
            [
                "tests/test_broken.py doesn't parse, so its tests can't be checked",
                "tests/test_new.py:1: test_new checks nothing: it has no assert, no "
                "pytest.raises and no other check",
            ],
        )

    def test_missing_rule_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(
                root, "rules/registry.toml", 'schema_version = 1\nrepo = "example"\n'
            )
            messages = [violation.message for violation in run_check(root)]
        self.assertEqual(messages, [f"rules/registry.toml has no rule {RULE_ID}"])


class TestRepository(unittest.TestCase):
    """Every test in the repository checks something, apart from the baseline."""

    def test_repository_has_no_violations(self) -> None:
        self.assertEqual([str(violation) for violation in run_check(REPO_ROOT)], [])


if __name__ == "__main__":
    unittest.main()
