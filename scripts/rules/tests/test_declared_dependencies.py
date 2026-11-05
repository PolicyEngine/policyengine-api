"""Tests for the declared-dependencies guard: deptry's findings, ratcheted."""

from __future__ import annotations

import shutil
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
    inline_ignore_violations,
    run_check,
    run_deptry,
    scanned_files_from_log,
    settings_violations,
    unparsed_file_violations,
    unscanned_file_violations,
)
from scripts.rules.makefile import job_make_commands
from scripts.rules.model import RuleException
from scripts.rules.resolve import workflow_jobs

FIXTURES = REPO_ROOT / "rules" / "fixtures" / RULE_ID
BASELINE_FILE = "rules/baselines/deptry.txt"
REQUIRED_TABLE = textwrap.dedent(
    """
    [tool.deptry]
    known_first_party = ["policyengine_api"]
    optional_dependencies_dev_groups = ["dev"]
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


def _write(root: Path, relative_path: str, text: str) -> None:
    file = root / relative_path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)


def _accepted_copy(directory: str) -> Path:
    """Copy the accepted fixture into ``directory`` and track it in a new git repo."""
    root = Path(directory) / "project"
    shutil.copytree(FIXTURES / "accepted", root)
    _git(root, "init", "--quiet")
    _git(root, "add", ".")
    return root


def _exception_at(path: str, package: str = "openai") -> RuleException:
    return RuleException(
        path=path, reason="Loads it.", match=package, category=NOT_IMPORTED
    )


def _job_text(workflow_text: str, job_id: str) -> str:
    """Return the lines of ``job_id``'s block in a workflow, up to the next job."""
    lines = workflow_text.splitlines()
    start = lines.index(f"  {job_id}:")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("  ") and not lines[index].startswith("   ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


class TestDeclaredDependenciesProof(unittest.TestCase):
    """Proof: deptry's findings in the rejected fixture fail, the accepted pass."""

    def test_rule_proof_declared_and_used(self) -> None:
        rejected_run = run_deptry(FIXTURES / "rejected")
        rejected = rejected_run.findings
        self.assertEqual(
            rejected_run.scanned_files, {"policyengine_api/application.py"}
        )
        self.assertEqual(
            _entries(rejected),
            {
                "DEP001 module_that_is_not_installed",
                "DEP002 asyncio",
                "DEP002 flask",
                "DEP003 starlette",
                "DEP004 pytest",
                "DEP005 asyncio",
            },
        )
        violations = compare(FIXTURES / "rejected", rejected, set(), BASELINE_FILE, ())
        self.assertEqual(len(violations), 6)
        self.assertEqual({violation.rule_id for violation in violations}, {RULE_ID})
        self.assertEqual(run_deptry(FIXTURES / "accepted").findings, [])


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
                "declared only as a development dependency",
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
                "exception for gcp/cloud_run/start.sh: no line of code in the file "
                "names gunicorn",
            ],
        )

    def test_a_comment_naming_the_package_does_not_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _root_with_start_script(
                directory,
                "# gunicorn used to run the app\n  # gunicorn\nexec hypercorn\n",
            )
            violations = compare(
                root,
                [_finding("DEP002", "gunicorn")],
                set(),
                BASELINE_FILE,
                (_start_script_exception("gunicorn"),),
            )
        self.assertEqual(
            [violation.message for violation in violations][1:],
            [
                "exception for gcp/cloud_run/start.sh: no line of code in the file "
                "names gunicorn"
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


class TestExceptionPaths(unittest.TestCase):
    """An exception names, by its exact path, one file the application runs from."""

    def _messages_for(self, path: str, files: tuple[str, ...] = ()) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for listed in files:
                _write(root, listed, "openai --serve\n")
            violations = compare(
                root,
                [_finding("DEP002", "openai")],
                set(),
                BASELINE_FILE,
                (_exception_at(path),),
            )
            return [violation.message for violation in violations]

    def test_a_glob_or_an_unnormalized_path_fails(self) -> None:
        for path in ("*.sh", "start.s[h]", "./start.sh", "/etc/start.sh"):
            with self.subTest(path=path):
                self.assertEqual(
                    self._messages_for(path, ("start.sh",))[1:],
                    [
                        f"exception for {path} must name one file by its exact "
                        "path from the repository root"
                    ],
                )

    def test_a_file_the_application_does_not_run_from_fails(self) -> None:
        for path in (
            "pyproject.toml",
            "uv.lock",
            "rules/registry.toml",
            "rules/baselines/deptry.txt",
            "docs/generated/rules.md",
            "changelog.d/4175.added.md",
            "tests/unit/test_server.py",
            "scripts/serve.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    self._messages_for(path, (path,))[1:],
                    [
                        f"exception for {path} names a file the application doesn't "
                        "run from: it must be a shell script, a Dockerfile or a "
                        "module in policyengine_api"
                    ],
                )

    def test_a_script_a_dockerfile_or_a_package_module_covers_the_finding(
        self,
    ) -> None:
        for path in (
            "gcp/cloud_run/start.sh",
            "gcp/cloud_run/Dockerfile",
            "docker/Dockerfile",
            "policyengine_api/data/orm.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(self._messages_for(path, (path,)), [])

    def test_a_missing_file_fails(self) -> None:
        self.assertEqual(
            self._messages_for("gcp/cloud_run/start.sh")[1:],
            ["exception for gcp/cloud_run/start.sh: the file doesn't exist"],
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
                "optional_dependencies_dev_groups": ["dev"],
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
            "optional_dependencies_dev_groups = ['dev']\n"
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
                "optional_dependencies_dev_groups",
            ],
        )

    def test_the_deprecated_name_for_the_dev_groups_fails(self) -> None:
        messages = self._violations_for(
            "[tool.deptry]\nknown_first_party = ['policyengine_api']\n"
            "pep621_dev_dependency_groups = ['dev']\n"
        )
        self.assertEqual(
            messages,
            [
                "pyproject.toml's [tool.deptry] doesn't set "
                "optional_dependencies_dev_groups",
                "pyproject.toml's [tool.deptry] sets pep621_dev_dependency_groups",
            ],
        )

    def test_a_dependency_with_an_environment_marker_fails(self) -> None:
        messages = self._violations_for(
            '[project]\ndependencies = ["flask", '
            "\"starlette; python_version < '3'\"]\n" + REQUIRED_TABLE
        )
        self.assertEqual(
            messages,
            [
                "pyproject.toml declares starlette; python_version < '3' with an "
                "environment marker, which deptry ignores"
            ],
        )

    def test_an_extra_that_is_not_a_dev_group_fails(self) -> None:
        messages = self._violations_for(
            "[project.optional-dependencies]\ndev = ['pytest']\n"
            "server = ['starlette']\n" + REQUIRED_TABLE
        )
        self.assertEqual(
            messages,
            [
                "pyproject.toml's [project.optional-dependencies] has the group "
                "server, which deptry counts as runtime dependencies"
            ],
        )


class TestIgnoreComments(unittest.TestCase):
    """An inline deptry ignore comment in the package fails."""

    def test_each_inline_ignore_comment_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write(
                root,
                "policyengine_api/module.py",
                "import yaml  # deptry: ignore\n"
                "import numpy  #deptry:ignore[DEP003]\n"
                "import flask\n",
            )
            _write(
                root, "policyengine_api/notebook.ipynb", '"import x  # deptry: ignore"'
            )
            _write(root, "scripts/tool.py", "import yaml  # deptry: ignore\n")
            messages = [
                violation.message for violation in inline_ignore_violations(root)
            ]
        self.assertEqual(
            messages,
            [
                "policyengine_api/module.py:1 has a deptry ignore comment",
                "policyengine_api/module.py:2 has a deptry ignore comment",
                "policyengine_api/notebook.ipynb:1 has a deptry ignore comment",
            ],
        )

    def test_the_package_has_no_inline_ignore_comment(self) -> None:
        self.assertEqual(inline_ignore_violations(REPO_ROOT), [])


class TestScannedFiles(unittest.TestCase):
    """Every tracked package file is scanned and parsed by deptry."""

    def test_reads_the_scanned_files_from_deptrys_log(self) -> None:
        log = (
            "Collecting Python files to scan...\n"
            "Python files to scan for imports:\n"
            "policyengine_api/a.py\n"
            "policyengine_api/sub/b.py\n"
            "\n"
            "Scanning 2 files...\n"
        )
        self.assertEqual(
            scanned_files_from_log(log),
            {"policyengine_api/a.py", "policyengine_api/sub/b.py"},
        )

    def test_a_log_without_the_scanned_files_is_an_error(self) -> None:
        with self.assertRaises(DeptryUnavailableError) as raised:
            scanned_files_from_log("Scanning 2 files...\n")
        self.assertIn("doesn't list the files it scanned", str(raised.exception))

    def test_a_tracked_file_deptry_did_not_scan_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _git(root, "init", "--quiet")
            _write(root, "policyengine_api/hidden.py", "import yaml\n")
            _write(root, "policyengine_api/module.py", "import flask\n")
            _git(root, "add", "policyengine_api")
            _write(root, "policyengine_api/untracked.py", "import yaml\n")
            messages = [
                violation.message
                for violation in unscanned_file_violations(
                    root, {"policyengine_api/module.py"}
                )
            ]
        self.assertEqual(
            messages,
            [
                "policyengine_api/hidden.py is tracked, but deptry didn't scan it, "
                "so its imports aren't checked"
            ],
        )

    def test_an_ignore_file_that_hides_a_package_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _accepted_copy(directory)
            _write(root, "policyengine_api/hidden.py", "import yaml\n")
            _git(root, "add", "policyengine_api/hidden.py")
            _write(root, ".ignore", "policyengine_api/hidden.py\n")
            run = run_deptry(root)
            messages = [
                violation.message
                for violation in unscanned_file_violations(root, run.scanned_files)
            ]
        self.assertEqual(run.findings, [])
        self.assertEqual(
            messages,
            [
                "policyengine_api/hidden.py is tracked, but deptry didn't scan it, "
                "so its imports aren't checked"
            ],
        )

    def test_an_ignore_file_listing_no_package_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _accepted_copy(directory)
            _write(root, ".ignore", "uv.lock\ndocs/generated/\n")
            run = run_deptry(root)
            self.assertEqual(unscanned_file_violations(root, run.scanned_files), [])

    def test_a_file_deptry_cannot_parse_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _accepted_copy(directory)
            _write(root, "policyengine_api/broken.py", "import yaml\ndef broken(:\n")
            run = run_deptry(root)
        self.assertEqual(run.unparsed_files, ("policyengine_api/broken.py",))
        self.assertEqual(
            [violation.message for violation in unparsed_file_violations(run)],
            [
                "deptry couldn't parse policyengine_api/broken.py, so it didn't "
                "check that file's imports"
            ],
        )


class TestWorkflows(unittest.TestCase):
    """Every CI job that runs the guards can run deptry in the uv.lock environment."""

    def test_every_job_running_the_guards_has_uv_on_python_3_12(self) -> None:
        guard_jobs = []
        for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
            workflow_text = workflow.read_text()
            header = workflow_text.split("\njobs:", 1)[0]
            for job in workflow_jobs(workflow)[0].values():
                # A job may run the guards through a make target, such as
                # pr.yml's make quality.
                commands = [
                    job.run_text,
                    *job_make_commands(REPO_ROOT, job.run_text),
                ]
                if not any("run_quality_guards.py" in command for command in commands):
                    continue
                guard_jobs.append(f"{workflow.name}:{job.id}")
                with self.subTest(job=f"{workflow.name}:{job.id}"):
                    self.assertTrue(
                        any(
                            uses.startswith("astral-sh/setup-uv@")
                            for uses in job.step_uses
                        )
                    )
                    self.assertIn(
                        'UV_PYTHON: "3.12"', _job_text(workflow_text, job.id) + header
                    )
                    self.assertTrue(
                        "uv sync --frozen --extra dev" in job.run_text
                        or "uv run --frozen --extra dev" in job.run_text
                    )
        self.assertEqual(
            guard_jobs, ["pr.yml:quality-guards", "push.yml:quality-guards"]
        )


class TestDeptryUnavailable(unittest.TestCase):
    """A deptry that cannot run is an error, never an empty set of findings."""

    def test_missing_uv_is_an_error(self) -> None:
        with (
            mock.patch("scripts.rules.declared_dependencies.shutil.which") as which,
            self.assertRaises(DeptryUnavailableError) as raised,
        ):
            which.return_value = None
            run_deptry(FIXTURES / "accepted")
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
            run_deptry(FIXTURES / "accepted")
        self.assertIn("exited with 2", str(raised.exception))
        self.assertIn("error: no such option", str(raised.exception))


class TestRepository(unittest.TestCase):
    """The repository has no deptry finding outside the baseline and exceptions."""

    def test_repository_has_no_violations(self) -> None:
        self.assertEqual([str(violation) for violation in run_check(REPO_ROOT)], [])


if __name__ == "__main__":
    unittest.main()
