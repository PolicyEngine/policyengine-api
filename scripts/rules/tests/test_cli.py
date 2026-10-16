"""Tests for the rules command line: what each command prints and returns."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.rules.ci_scripts import Findings
from scripts.rules.cli import main
from scripts.rules.guard import GuardResult
from scripts.rules.model import Violation
from scripts.rules.tests.support import REGISTRY, Repo

MISSING_REGISTRY = (
    "  - [registry] schema: rules/registry.toml is missing. "
    "Fix: create rules/registry.toml."
)
DUPLICATE_CATEGORY = (
    "  - [registry] schema: duplicate category 'layers'. "
    "Fix: give each category a unique id."
)
CI_SCRIPTS_TABLE = """
[ci_scripts]
workflows = ".github/workflows/*.yml"
scripts_dir = ".github/scripts"
test_globs = ["tests/**/test_*.py"]
multiline_baseline = "rules/baselines/ci-multiline-run.txt"
untested_baseline = "rules/baselines/ci-untested-scripts.txt"
shellcheck_baseline = "rules/baselines/ci-shellcheck.txt"
"""


def run_cli(*argv: str) -> tuple[int, list[str]]:
    """Run the command line and return its exit status and printed lines."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        status = main(list(argv))
    return status, output.getvalue().splitlines()


def with_duplicate_category(repo: Repo) -> None:
    """Append a second category with an existing id, which validation rejects."""
    repo.write(
        "rules/registry.toml",
        repo.read("rules/registry.toml")
        + '\n[[category]]\nid = "layers"\ntitle = "Layers again"\n',
    )


class ValidateCommandTest(unittest.TestCase):
    def test_valid_registry_passes(self) -> None:
        with Repo() as repo:
            self.assertEqual(
                run_cli("validate", "--root", str(repo.root)), (0, ["rules: passed"])
            )

    def test_missing_registry_fails(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                run_cli("validate", "--root", root),
                (1, [MISSING_REGISTRY, "rules: failed"]),
            )

    def test_violations_are_listed(self) -> None:
        with Repo(render=False) as repo:
            with_duplicate_category(repo)
            self.assertEqual(
                run_cli("validate", "--root", str(repo.root)),
                (1, [DUPLICATE_CATEGORY, "rules: failed"]),
            )


class RenderCommandTest(unittest.TestCase):
    def test_render_writes_both_views(self) -> None:
        with Repo(render=False) as repo:
            self.assertEqual(
                run_cli("render", "--root", str(repo.root)),
                (0, ["wrote docs/generated/rules.md", "wrote AGENTS.md"]),
            )
            self.assertTrue((repo.root / "docs/generated/rules.md").is_file())
            self.assertIn("BEGIN GENERATED: rules", repo.read("AGENTS.md"))

    def test_render_refuses_an_invalid_registry(self) -> None:
        with Repo(render=False) as repo:
            with_duplicate_category(repo)
            self.assertEqual(
                run_cli("render", "--root", str(repo.root)),
                (
                    1,
                    [
                        "render refused: fix the registry first",
                        DUPLICATE_CATEGORY,
                        "rules: failed",
                    ],
                ),
            )
            self.assertFalse((repo.root / "docs/generated/rules.md").exists())

    def test_render_reports_a_missing_registry(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                run_cli("render", "--root", root),
                (1, [MISSING_REGISTRY, "rules: failed"]),
            )
            self.assertFalse((Path(root) / "docs").exists())


class GuardCommandTest(unittest.TestCase):
    def test_guard_prints_notes_then_violations(self) -> None:
        result = GuardResult(
            violations=[Violation("ex.rule", "ci", "job is missing", "add the job")],
            notes=["base ref unavailable"],
        )
        with (
            Repo(render=False) as repo,
            mock.patch("scripts.rules.cli.run_guard", return_value=result) as guard,
        ):
            self.assertEqual(
                run_cli("guard", "--root", str(repo.root), "--base-ref", "origin/main"),
                (
                    1,
                    [
                        "note: base ref unavailable",
                        "  - [ex.rule] ci: job is missing. Fix: add the job.",
                        "rules: failed",
                    ],
                ),
            )
            guard.assert_called_once_with(repo.root.resolve(), base_ref="origin/main")

    def test_clean_guard_passes(self) -> None:
        with (
            Repo(render=False) as repo,
            mock.patch(
                "scripts.rules.cli.run_guard", return_value=GuardResult()
            ) as guard,
        ):
            self.assertEqual(
                run_cli("guard", "--root", str(repo.root)), (0, ["rules: passed"])
            )
            guard.assert_called_once_with(repo.root.resolve(), base_ref=None)


class CiScriptsCommandTest(unittest.TestCase):
    def test_check_prints_notes_and_violations(self) -> None:
        violation = Violation(None, "ci-scripts", "untested script x.sh", "test it")
        with (
            Repo(render=False) as repo,
            mock.patch(
                "scripts.rules.ci_scripts.run_check",
                return_value=([violation], ["shellcheck is not installed"]),
            ) as run_check,
        ):
            self.assertEqual(
                run_cli("ci-scripts", "--root", str(repo.root)),
                (
                    1,
                    [
                        "note: shellcheck is not installed",
                        "  - [registry] ci-scripts: untested script x.sh. "
                        "Fix: test it.",
                        "rules: failed",
                    ],
                ),
            )
            run_check.assert_called_once_with(repo.root.resolve())

    def test_check_without_findings_passes(self) -> None:
        with (
            Repo(render=False) as repo,
            mock.patch("scripts.rules.ci_scripts.run_check", return_value=([], [])),
        ):
            self.assertEqual(
                run_cli("ci-scripts", "--root", str(repo.root)), (0, ["rules: passed"])
            )

    def test_write_baselines_needs_a_registry(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(
                run_cli("ci-scripts", "--root", root, "--write-baselines"),
                (1, [MISSING_REGISTRY, "rules: failed"]),
            )

    def test_write_baselines_needs_a_ci_scripts_table(self) -> None:
        with Repo(render=False) as repo:
            self.assertEqual(
                run_cli("ci-scripts", "--root", str(repo.root), "--write-baselines"),
                (1, ["  - no [ci_scripts] table", "rules: failed"]),
            )

    def test_write_baselines_reports_schema_problems_first(self) -> None:
        with Repo(render=False) as repo:
            repo.edit("rules/registry.toml", 'repo = "example"', "repo = 7")
            self.assertEqual(
                run_cli("ci-scripts", "--root", str(repo.root), "--write-baselines"),
                (
                    1,
                    [
                        "  - [registry] schema: registry.repo must be a non-empty "
                        "string. Fix: set repo.",
                        "rules: failed",
                    ],
                ),
            )

    def test_write_baselines_records_the_findings(self) -> None:
        findings = Findings(
            multiline={"wf.yml :: build :: Build"},
            untested={".github/scripts/b.sh", ".github/scripts/a.sh"},
            shellcheck=None,
        )
        with (
            Repo({"rules/registry.toml": REGISTRY + CI_SCRIPTS_TABLE}) as repo,
            mock.patch("scripts.rules.ci_scripts.find", return_value=findings) as find,
        ):
            self.assertEqual(
                run_cli("ci-scripts", "--root", str(repo.root), "--write-baselines"),
                (0, ["wrote ci_scripts baselines; update the rules' baseline counts"]),
            )
            find.assert_called_once()
            self.assertEqual(find.call_args.args[1], repo.root.resolve())
            header = "# Tolerated existing violations. This list may only shrink.\n"
            self.assertEqual(
                repo.read("rules/baselines/ci-multiline-run.txt"),
                header + "wf.yml :: build :: Build\n",
            )
            self.assertEqual(
                repo.read("rules/baselines/ci-untested-scripts.txt"),
                header + ".github/scripts/a.sh\n.github/scripts/b.sh\n",
            )
            self.assertFalse((repo.root / "rules/baselines/ci-shellcheck.txt").exists())


if __name__ == "__main__":
    unittest.main()
