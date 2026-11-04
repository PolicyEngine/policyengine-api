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
            ("tests/unit/fixtures/test_probe.py", True),
            ("tests/to_refactor/fixtures/test_households.py", True),
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


def _unchecked_source(source: str, files: dict[str, str] | None = None) -> list[str]:
    """Return the unchecked tests in ``source``, with ``files`` beside it."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative_path, text in (files or {}).items():
            _write(root, relative_path, text)
        return _unchecked(root, "tests/test_module.py", textwrap.dedent(source))


class TestCollection(unittest.TestCase):
    """The guard reads the tests pytest collects, and only those."""

    def test_inherited_and_conditional_tests_are_read(self) -> None:
        source = """
            import unittest


            class SharedChecks:
                def test_shared(self):
                    print("nothing")


            class TestUS(SharedChecks):
                pass


            class BaseCase(unittest.TestCase):
                pass


            class ServiceTests(BaseCase):
                def test_service(self):
                    print("nothing")


            if True:
                def test_in_if_block():
                    print("nothing")
            """
        self.assertEqual(
            _unchecked_source(source),
            ["TestUS::test_shared", "ServiceTests::test_service", "test_in_if_block"],
        )

    def test_a_test_case_base_imported_from_a_test_module_counts(self) -> None:
        files = {
            "tests/support.py": """
                import unittest


                class BaseCase(unittest.TestCase):
                    pass
                """
        }
        source = """
            from tests.support import BaseCase


            class ServiceTests(BaseCase):
                def test_service(self):
                    print("nothing")
            """
        self.assertEqual(
            _unchecked_source(source, files), ["ServiceTests::test_service"]
        )

    def test_classes_pytest_does_not_collect_are_skipped(self) -> None:
        source = """
            import unittest


            class TestHasInit:
                def __init__(self):
                    self.value = 1

                def test_not_collected(self):
                    print("nothing")


            class TestSwitchedOff:
                __test__ = False

                def test_not_collected(self):
                    print("nothing")


            class Case(unittest.TestCase):
                class TestNestedInCase:
                    def test_not_collected(self):
                        print("nothing")
            """
        self.assertEqual(_unchecked_source(source), [])

    def test_a_module_switched_off_is_skipped(self) -> None:
        source = """
            __test__ = False


            def test_not_collected():
                print("nothing")
            """
        self.assertEqual(_unchecked_source(source), [])

    def test_a_byte_order_mark_is_read(self) -> None:
        self.assertEqual(
            _unchecked_source("﻿def test_bom():\n    print(1)\n"), ["test_bom"]
        )


class TestHelperResolution(unittest.TestCase):
    """A call counts as a check only through the helper it really calls."""

    def test_a_method_of_another_object_is_not_a_helper(self) -> None:
        source = """
            class FakeClient:
                def get(self, url):
                    assert url


            def test_real_client(real_client):
                real_client.get("/anything")


            def test_other(handler):
                def respond(value):
                    assert value

                respond(1)


            def test_handler(handler):
                handler.respond(1)
            """
        self.assertEqual(
            _unchecked_source(source), ["test_real_client", "test_handler"]
        )

    def test_a_method_of_the_same_class_is_a_helper(self) -> None:
        source = """
            class TestThing:
                def check(self, value):
                    assert value

                def test_uses_its_helper(self):
                    self.check(1)
            """
        self.assertEqual(_unchecked_source(source), [])

    def test_a_nested_function_elsewhere_does_not_hide_an_import(self) -> None:
        files = {"tests/support.py": "def check(value):\n    assert value\n"}
        source = """
            from tests.support import check


            def test_a():
                check(1)


            def test_b():
                def check(value):
                    return value

                check(1)
            """
        self.assertEqual(_unchecked_source(source, files), ["test_b"])

    def test_helpers_that_call_each_other_give_the_same_result_in_any_order(
        self,
    ) -> None:
        helpers = """
            def check_tree(node):
                check_children(node)
                if node is not None:
                    assert node is not None


            def check_children(node):
                for child in node:
                    check_tree(child)
            """
        tests = (
            "\n\ndef test_tree():\n    check_tree([])\n",
            "\n\ndef test_children():\n    check_children([])\n",
        )
        for ordered in (tests, tests[::-1]):
            with self.subTest(first=ordered[0].split("(")[0].strip()):
                source = textwrap.dedent(helpers) + "".join(ordered)
                self.assertEqual(_unchecked_source(source), [])

    def test_an_import_inside_the_test_is_followed(self) -> None:
        files = {"tests/support.py": "def check_response(value):\n    assert value\n"}
        source = """
            def test_imports_inside():
                from tests.support import check_response

                check_response(1)
            """
        self.assertEqual(_unchecked_source(source, files), [])

    def test_aliased_pytest_and_assert_functions_count(self) -> None:
        source = """
            import pytest as pt
            from numpy.testing import assert_allclose as close


            def test_pytest_alias():
                with pt.raises(ZeroDivisionError):
                    _ = 1 / 0


            def test_assert_alias():
                close(1.0, 1.0)
            """
        self.assertEqual(_unchecked_source(source), [])

    def test_production_code_is_not_a_helper(self) -> None:
        files = {
            "policyengine_api/publication.py": """
                def publish(catalog):
                    assert_matches(catalog)


                def assert_matches(catalog):
                    if not catalog:
                        raise ValueError
                """
        }
        source = """
            from policyengine_api.publication import publish


            def test_publishes():
                publish([1])
            """
        self.assertEqual(_unchecked_source(source, files), ["test_publishes"])

    def test_only_the_test_body_and_the_stand_ins_it_uses_count(self) -> None:
        source = """
            import pytest


            def assert_positive(value):
                assert value > 0
                return value


            def test_unused_nested_function():
                def never_called():
                    assert False

                print(2)


            @pytest.mark.parametrize("value", [assert_positive(1)])
            def test_decorator_only(value):
                print(value)


            def test_default_only(value=assert_positive(1)):
                print(value)


            def test_stand_in_class(service):
                class FakeStore:
                    def save(self, row):
                        assert row

                service(FakeStore())
            """
        self.assertEqual(
            _unchecked_source(source),
            [
                "test_unused_nested_function",
                "test_decorator_only",
                "test_default_only",
            ],
        )

    def test_a_helper_module_that_does_not_parse_is_not_followed(self) -> None:
        files = {"tests/support.py": "def check(value:\n"}
        source = """
            from tests.support import check


            def test_uses_broken_helper():
                check(1)


            def test_checks_itself():
                assert True
            """
        self.assertEqual(_unchecked_source(source, files), ["test_uses_broken_helper"])


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
