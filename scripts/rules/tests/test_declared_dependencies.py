"""Tests for the declared-dependencies guard: deptry's findings, ratcheted."""

from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from scripts.rules.declared_dependencies import (
    NOT_IMPORTED,
    REPO_ROOT,
    REQUIRED_SETTINGS,
    RULE_ID,
    DeptryUnavailableError,
    Finding,
    compare,
    deptry_findings,
    run_check,
    settings_violations,
)
from scripts.rules.model import RuleException

FIXTURES = REPO_ROOT / "rules" / "fixtures" / RULE_ID
BASELINE_FILE = "rules/baselines/deptry.txt"
REQUIRED_TABLE = textwrap.dedent(
    """
    [tool.deptry]
    known_first_party = ["policyengine_api"]
    pep621_dev_dependency_groups = ["dev"]
    """
)


def _entries(findings: list[Finding]) -> set[str]:
    return {finding.entry for finding in findings}


def _finding(code: str, module: str, file: str = "pyproject.toml") -> Finding:
    line = None if file == "pyproject.toml" else 3
    return Finding(code, module, file, line, f"deptry's message for {module}")


def _start_script_exception(package: str) -> RuleException:
    return RuleException(
        path="gcp/cloud_run/start.sh",
        reason="The start command runs it.",
        match=package,
        category=NOT_IMPORTED,
    )


def _root_with_start_script(directory: str, text: str) -> Path:
    root = Path(directory)
    (root / "gcp" / "cloud_run").mkdir(parents=True)
    (root / "gcp" / "cloud_run" / "start.sh").write_text(text)
    return root


class TestDeclaredDependenciesProof(unittest.TestCase):
    """Proof: deptry's findings in the rejected fixture fail, the accepted pass."""

    def test_rule_proof_declared_and_used(self) -> None:
        rejected = deptry_findings(FIXTURES / "rejected")
        self.assertEqual(
            _entries(rejected),
            {
                "DEP001 module_that_is_not_installed",
                "DEP002 flask",
                "DEP003 starlette",
                "DEP004 pytest",
            },
        )
        violations = compare(FIXTURES / "rejected", rejected, set(), BASELINE_FILE, ())
        self.assertEqual(len(violations), 4)
        self.assertEqual({violation.rule_id for violation in violations}, {RULE_ID})
        self.assertEqual(deptry_findings(FIXTURES / "accepted"), [])


class TestFindingMessages(unittest.TestCase):
    """Each deptry code gets a message that says where and what to do."""

    def test_each_code_names_the_problem_and_the_fix(self) -> None:
        cases = {
            _finding("DEP001", "yaml", "policyengine_api/config.py"): (
                "yaml is imported in policyengine_api/config.py:3, but no "
                "declared dependency provides it",
                "declare the distribution that provides it",
            ),
            _finding("DEP002", "faiss-cpu"): (
                "faiss-cpu is declared in pyproject.toml, but policyengine_api "
                "never imports it",
                'category = "not-imported-package"',
            ),
            _finding("DEP003", "starlette", "policyengine_api/asgi.py"): (
                "starlette is imported in policyengine_api/asgi.py:3, but is "
                "installed only as a dependency of another package",
                "declare its distribution in [project].dependencies",
            ),
            _finding("DEP004", "pytest", "policyengine_api/asgi.py"): (
                "pytest is imported in policyengine_api/asgi.py:3, but is "
                "declared only in the dev extra",
                "move it to [project].dependencies",
            ),
            _finding("DEP005", "json"): (
                "json is declared in pyproject.toml, but is part of the "
                "standard library",
                "remove it from pyproject.toml",
            ),
        }
        for finding, (message, fix_text) in cases.items():
            with self.subTest(code=finding.code):
                (violation,) = compare(REPO_ROOT, [finding], set(), BASELINE_FILE, ())
                self.assertEqual(violation.message, message)
                self.assertIn(fix_text, violation.fix)

    def test_repeated_imports_are_one_violation_naming_the_others(self) -> None:
        findings = [
            _finding("DEP003", "starlette", "policyengine_api/asgi.py"),
            _finding("DEP003", "starlette", "policyengine_api/routes.py"),
            _finding("DEP003", "starlette", "policyengine_api/health.py"),
        ]
        (violation,) = compare(REPO_ROOT, findings, set(), BASELINE_FILE, ())
        self.assertEqual(
            violation.message,
            "starlette is imported in policyengine_api/asgi.py:3 and 2 other "
            "places, but is installed only as a dependency of another package",
        )

    def test_an_unknown_code_keeps_deptrys_message(self) -> None:
        (violation,) = compare(
            REPO_ROOT, [_finding("DEP999", "pkg")], set(), BASELINE_FILE, ()
        )
        self.assertEqual(violation.message, "DEP999: deptry's message for pkg")


class TestBaseline(unittest.TestCase):
    """The baseline tolerates listed findings and may only shrink."""

    def test_unlisted_finding_fails(self) -> None:
        violations = compare(
            REPO_ROOT,
            [_finding("DEP002", "openai"), _finding("DEP002", "rq")],
            {"DEP002 openai"},
            BASELINE_FILE,
            (),
        )
        self.assertEqual(
            [violation.message for violation in violations],
            ["rq is declared in pyproject.toml, but policyengine_api never imports it"],
        )

    def test_listed_finding_passes(self) -> None:
        findings = [_finding("DEP003", "numpy", "policyengine_api/utils/json.py")]
        self.assertEqual(
            compare(REPO_ROOT, findings, {"DEP003 numpy"}, BASELINE_FILE, ()), []
        )

    def test_listed_entry_deptry_no_longer_reports_fails(self) -> None:
        violations = compare(REPO_ROOT, [], {"DEP003 numpy"}, BASELINE_FILE, ())
        self.assertEqual(
            [str(violation) for violation in violations],
            [
                f"[{RULE_ID}] declared-dependencies: baseline entry no longer "
                "applies: DEP003 numpy. Fix: remove it from "
                f"{BASELINE_FILE} and lower the rule's baseline count."
            ],
        )


class TestNotImportedExceptions(unittest.TestCase):
    """An exception tolerates an unused finding for a package loaded by name."""

    def test_exception_covers_an_unused_package_its_file_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _root_with_start_script(directory, "exec gunicorn app\n")
            violations = compare(
                root,
                [_finding("DEP002", "gunicorn")],
                set(),
                BASELINE_FILE,
                (_start_script_exception("gunicorn"),),
            )
        self.assertEqual(violations, [])

    def test_exception_does_not_cover_other_codes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _root_with_start_script(directory, "exec gunicorn app\n")
            violations = compare(
                root,
                [
                    _finding("DEP002", "gunicorn"),
                    _finding("DEP003", "gunicorn", "policyengine_api/asgi.py"),
                ],
                set(),
                BASELINE_FILE,
                (_start_script_exception("gunicorn"),),
            )
        self.assertEqual(
            [violation.message for violation in violations],
            [
                "gunicorn is imported in policyengine_api/asgi.py:3, but is "
                "installed only as a dependency of another package"
            ],
        )

    def test_exception_whose_file_no_longer_names_the_package_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _root_with_start_script(directory, "exec hypercorn app\n")
            violations = compare(
                root,
                [_finding("DEP002", "gunicorn")],
                set(),
                BASELINE_FILE,
                (_start_script_exception("gunicorn"),),
            )
        self.assertEqual(
            [violation.message for violation in violations],
            [
                "gunicorn is declared in pyproject.toml, but policyengine_api "
                "never imports it",
                "exception for gcp/cloud_run/start.sh: the file doesn't name gunicorn",
            ],
        )

    def test_exception_for_a_package_deptry_no_longer_reports_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _root_with_start_script(directory, "exec gunicorn app\n")
            violations = compare(
                root, [], set(), BASELINE_FILE, (_start_script_exception("gunicorn"),)
            )
        self.assertEqual(
            [violation.message for violation in violations],
            [
                "exception for gcp/cloud_run/start.sh no longer applies: deptry "
                "doesn't report gunicorn as unused"
            ],
        )

    def test_exception_needs_the_category_and_a_match(self) -> None:
        exceptions = (
            RuleException(path="gcp/cloud_run/start.sh", reason="Runs it."),
            RuleException(
                path="gcp/cloud_run/start.sh",
                reason="Runs it.",
                match="gunicorn",
                category="pinned-tool",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = _root_with_start_script(directory, "exec gunicorn app\n")
            messages = [
                violation.message
                for violation in compare(root, [], set(), BASELINE_FILE, exceptions)
            ]
        self.assertEqual(
            messages,
            [
                "exception for gcp/cloud_run/start.sh has no match naming the package",
                "exception for gcp/cloud_run/start.sh has category None; this "
                f"rule allows only '{NOT_IMPORTED}'",
                "exception for gcp/cloud_run/start.sh has category 'pinned-tool'; "
                f"this rule allows only '{NOT_IMPORTED}'",
            ],
        )


class TestSettings(unittest.TestCase):
    """pyproject.toml's [tool.deptry] holds only the settings the rule requires."""

    def _violations_for(self, pyproject_text: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(pyproject_text)
            return [violation.message for violation in settings_violations(root)]

    def test_required_settings_pass(self) -> None:
        self.assertEqual(self._violations_for(REQUIRED_TABLE), [])
        self.assertEqual(
            REQUIRED_SETTINGS,
            {
                "known_first_party": ["policyengine_api"],
                "pep621_dev_dependency_groups": ["dev"],
            },
        )

    def test_an_ignore_setting_fails(self) -> None:
        messages = self._violations_for(
            REQUIRED_TABLE + "[tool.deptry.per_rule_ignores]\nDEP003 = ['numpy']\n"
        )
        self.assertEqual(
            messages,
            ["pyproject.toml's [tool.deptry] sets per_rule_ignores"],
        )

    def test_a_changed_setting_fails(self) -> None:
        messages = self._violations_for(
            "[tool.deptry]\nknown_first_party = ['policyengine_api', 'scripts']\n"
            "pep621_dev_dependency_groups = ['dev']\n"
        )
        self.assertEqual(
            messages,
            [
                "pyproject.toml's [tool.deptry] sets known_first_party to "
                "['policyengine_api', 'scripts'], not ['policyengine_api']"
            ],
        )

    def test_a_missing_table_fails(self) -> None:
        self.assertEqual(
            self._violations_for("[project]\nname = 'example'\n"),
            [
                "pyproject.toml's [tool.deptry] doesn't set known_first_party",
                "pyproject.toml's [tool.deptry] doesn't set "
                "pep621_dev_dependency_groups",
            ],
        )


class TestDeptryUnavailable(unittest.TestCase):
    """A deptry that cannot run is an error, never an empty set of findings."""

    def test_missing_uv_is_an_error(self) -> None:
        with (
            mock.patch("scripts.rules.declared_dependencies.shutil.which") as which,
            self.assertRaises(DeptryUnavailableError) as raised,
        ):
            which.return_value = None
            deptry_findings(FIXTURES / "accepted")
        self.assertIn("uv is not installed", str(raised.exception))

    def test_deptry_that_writes_no_report_is_an_error(self) -> None:
        failed_run = subprocess.CompletedProcess(
            args=["uv"], returncode=2, stdout="", stderr="error: no such option\n"
        )
        with (
            mock.patch(
                "scripts.rules.declared_dependencies.subprocess.run",
                return_value=failed_run,
            ),
            self.assertRaises(DeptryUnavailableError) as raised,
        ):
            deptry_findings(FIXTURES / "accepted")
        self.assertIn("exited with 2", str(raised.exception))
        self.assertIn("error: no such option", str(raised.exception))


class TestRepository(unittest.TestCase):
    """The repository has no deptry finding outside the baseline and exceptions."""

    def test_repository_has_no_violations(self) -> None:
        self.assertEqual([str(violation) for violation in run_check(REPO_ROOT)], [])


if __name__ == "__main__":
    unittest.main()
