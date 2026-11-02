"""Tests for the file-length guard: Python files stay under their line limit."""

from __future__ import annotations

import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path

from scripts.rules.file_length import (
    REPO_ROOT,
    RULE_ID,
    SOURCE_LINE_LIMIT,
    TEST_LINE_LIMIT,
    is_excluded,
    is_test_code,
    line_limit,
    oversized_files,
    physical_line_count,
    run_check,
)
from scripts.rules.load import load_registry

FIXTURES = REPO_ROOT / "rules" / "fixtures" / RULE_ID
MIGRATION_REVISIONS = "migrations/*/versions/*.py"


def _write_lines(file: Path, line_count: int) -> None:
    """Write ``line_count`` short statements to ``file``, creating its directories."""
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        "".join(f"value_{index} = {index}\n" for index in range(line_count))
    )


def _write_tree(tree_fixture: Path, root: Path) -> dict[str, int]:
    """Write the files a tree fixture lists under ``root``; return its path counts."""
    files = tomllib.loads(tree_fixture.read_text())["files"]
    for relative_path, line_count in files.items():
        _write_lines(root / relative_path, line_count)
    return files


def _registered_exclusions() -> list[str]:
    """Return the exception paths the real registry gives the file-length rule."""
    registry, _ = load_registry(REPO_ROOT)
    if registry is None:
        msg = "rules/registry.toml did not load"
        raise AssertionError(msg)
    rule = registry.rule(RULE_ID)
    if rule is None:
        msg = f"rules/registry.toml has no rule {RULE_ID}"
        raise AssertionError(msg)
    return [exception.path for exception in rule.exceptions]


def _registry_with_rule(baseline_block: str) -> str:
    """Return a registry holding only the file-length rule, with ``baseline_block``."""
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
        statement = "Python files stay short."
        rationale = "docs/guide.md"
        scope = ["**/*.py"]
        tier = "mechanical"
        status = "ratcheted"
        autofix = false
        [rule.enforcer]
        kind = "quality-guard"
        name = "file-length"
        [[rule.ci]]
        workflow = ".github/workflows/pr.yml"
        job = "quality-guards"
        invocation = "run_quality_guards.py"
        {baseline_block}
        [[rule.exception]]
        path = "{MIGRATION_REVISIONS}"
        category = "migration-revision"
        reason = "Applied revisions are never edited."
        """
    )


class TestFileLengthProof(unittest.TestCase):
    """Proof: the guard rejects files one line over their limit, accepts them at it."""

    def test_rule_proof_file_length(self) -> None:
        excluded_patterns = _registered_exclusions()
        self.assertIn(MIGRATION_REVISIONS, excluded_patterns)
        with tempfile.TemporaryDirectory() as bad_directory:
            bad_root = Path(bad_directory)
            bad_files = _write_tree(FIXTURES / "bad_tree.toml", bad_root)
            reported = {
                oversized.path: oversized.line_count
                for oversized in oversized_files(bad_root, excluded_patterns)
            }
            self.assertEqual(reported, bad_files)
        with tempfile.TemporaryDirectory() as good_directory:
            good_root = Path(good_directory)
            _write_tree(FIXTURES / "good_tree.toml", good_root)
            self.assertEqual(oversized_files(good_root, excluded_patterns), [])


class TestLimits(unittest.TestCase):
    """Which limit applies to a path, and which paths the rule excludes."""

    def test_test_code_is_under_tests_or_fixtures_or_a_conftest(self) -> None:
        for path in (
            "tests/unit/test_service.py",
            "scripts/rules/tests/support.py",
            "rules/fixtures/example/bad_module.py",
            "tests/fixtures/sample.py",
            "conftest.py",
            "policyengine_api/conftest.py",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_test_code(path))
                self.assertEqual(line_limit(path), TEST_LINE_LIMIT)

    def test_everything_else_is_a_source_file(self) -> None:
        for path in (
            "policyengine_api/services/economy_service.py",
            "policyengine_api/test_helpers.py",
            "scripts/run_quality_guards.py",
            ".github/scripts/sync_issues.py",
            "tests.py",
        ):
            with self.subTest(path=path):
                self.assertFalse(is_test_code(path))
                self.assertEqual(line_limit(path), SOURCE_LINE_LIMIT)

    def test_exclusion_matches_whole_paths_only(self) -> None:
        patterns = [MIGRATION_REVISIONS]
        self.assertTrue(is_excluded("migrations/v1/versions/abc_revision.py", patterns))
        self.assertFalse(is_excluded("migrations/v1/env.py", patterns))
        self.assertFalse(
            is_excluded("vendor/migrations/v1/versions/abc_revision.py", patterns)
        )


class TestPhysicalLineCount(unittest.TestCase):
    """Lines are counted as Python reads them."""

    def test_counts_each_line_ending_style(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "module.py"
            for content, expected_count in (
                (b"", 0),
                (b"first\nsecond\n", 2),
                (b"first\nsecond", 2),
                (b"first\r\nsecond\r\n", 2),
                (b"first\rsecond\r", 2),
                (b"first\n\n\n", 3),
                (b"page\x0cbreak\n", 1),
            ):
                with self.subTest(content=content):
                    file.write_bytes(content)
                    self.assertEqual(physical_line_count(file), expected_count)


class TestBaseline(unittest.TestCase):
    """The baseline tolerates listed oversized files and may only shrink."""

    def _root_with(self, directory: str, baseline_entries: list[str] | None) -> Path:
        root = Path(directory)
        baseline_block = ""
        if baseline_entries is not None:
            baseline_block = textwrap.dedent(
                f"""
                [rule.baseline]
                file = "rules/baselines/file-length.txt"
                count = {len(baseline_entries)}
                """
            )
            baseline = root / "rules" / "baselines" / "file-length.txt"
            baseline.parent.mkdir(parents=True)
            baseline.write_text(
                "# Tolerated oversized files.\n"
                + "".join(f"{entry}\n" for entry in baseline_entries)
            )
        (root / "rules").mkdir(exist_ok=True)
        (root / "rules" / "registry.toml").write_text(
            _registry_with_rule(baseline_block)
        )
        _write_lines(root / "pkg" / "large_module.py", SOURCE_LINE_LIMIT + 1)
        _write_lines(root / "pkg" / "small_module.py", 10)
        _write_lines(root / "migrations" / "v2" / "versions" / "0001_base.py", 2000)
        return root

    def test_unlisted_oversized_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            violations = run_check(self._root_with(directory, None))
        self.assertEqual(
            [str(violation) for violation in violations],
            [
                f"[{RULE_ID}] file-length: pkg/large_module.py has 801 lines, over "
                "the 800-line limit for source files. Fix: split it by "
                "responsibility into modules under the limit, keeping its public "
                "import path (docs/engineering/skills/file-length.md)."
            ],
        )

    def test_listed_oversized_file_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root_with(directory, ["pkg/large_module.py"])
            self.assertEqual(run_check(root), [])

    def test_listed_file_within_its_limit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root_with(
                directory,
                ["pkg/large_module.py", "pkg/small_module.py", "pkg/removed.py"],
            )
            messages = [violation.message for violation in run_check(root)]
        self.assertEqual(
            messages,
            [
                "baseline entry no longer applies: pkg/removed.py does not exist",
                "baseline entry no longer applies: pkg/small_module.py has 10 "
                "lines, within the 800-line limit for source files",
            ],
        )

    def test_missing_rule_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "rules").mkdir()
            (root / "rules" / "registry.toml").write_text(
                'schema_version = 1\nrepo = "example"\n'
            )
            messages = [violation.message for violation in run_check(root)]
        self.assertEqual(messages, [f"rules/registry.toml has no rule {RULE_ID}"])


class TestRepository(unittest.TestCase):
    """The repository has no oversized file outside the baseline."""

    def test_repository_has_no_violations(self) -> None:
        self.assertEqual([str(violation) for violation in run_check(REPO_ROOT)], [])


if __name__ == "__main__":
    unittest.main()
