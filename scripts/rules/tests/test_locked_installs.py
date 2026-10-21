"""Tests for the locked-installs guard: Python packages come from uv.lock."""

from __future__ import annotations

import subprocess
import unittest
from datetime import date
from pathlib import Path

from scripts.rules.load import load_text
from scripts.rules.locked_installs import (
    INSTALL_RULE,
    REPO_ROOT,
    TEST_RULE,
    install_violations,
    scanned_files,
    test_command_violations,
    unlocked_install_sites,
    unlocked_test_commands,
)
from scripts.rules.model import RuleException

FIXTURES = Path(__file__).parent / "fixtures" / "locked_installs"
PINNED_SHELLCHECK = RuleException(
    path=".github/workflows/ci.yml",
    reason="shellcheck runs outside the project",
    match='pip install "shellcheck-py==0.11.0.1"',
    category="pinned-tool",
)


def _site_labels(root: Path) -> set[str]:
    return {f"{site.path}: {site.command}" for site in unlocked_install_sites(root)}


class TestLockedInstallsProof(unittest.TestCase):
    """Proof: the scanner rejects installs that bypass uv.lock, accepts locked ones."""

    def test_rule_proof_install_from_lock(self) -> None:
        self.assertEqual(
            _site_labels(FIXTURES / "install_bad"),
            {
                '.github/workflows/ci.yml: pip install -e ".[dev]"',
                ".github/workflows/ci.yml: uv sync --extra dev",
                ".github/workflows/ci.yml: uv run python app.py",
                ".github/workflows/ci.yml: uvx ruff check .",
                ".github/scripts/setup.sh: uv pip install requests",
                "Makefile: uv sync --extra dev",
                "Dockerfile: RUN pip install requests",
                'modal_app.py: .pip_install("numpy")',
            },
        )
        self.assertEqual(
            install_violations(FIXTURES / "install_good", (PINNED_SHELLCHECK,)), []
        )


class TestTestFromLockProof(unittest.TestCase):
    """Proof: every test command runs through uv run --frozen or --locked."""

    def test_rule_proof_test_from_lock(self) -> None:
        self.assertEqual(
            {
                f"{site.path}: {site.command}"
                for site in unlocked_test_commands(FIXTURES / "test_bad")
            },
            {
                ".github/workflows/ci.yml: python -m pytest tests",
                ".github/scripts/run_tests.sh: coverage run -m pytest tests",
                ".github/scripts/run_tests.sh: python -m unittest discover -s tests",
                "Makefile: pytest tests",
            },
        )
        self.assertEqual(test_command_violations(FIXTURES / "test_good", ()), [])

    def test_unlocked_test_command_names_the_test_rule(self) -> None:
        violations = test_command_violations(FIXTURES / "test_bad", ())

        self.assertEqual({violation.rule_id for violation in violations}, {TEST_RULE})
        self.assertIn("outside the uv.lock environment", violations[0].message)


class TestInstallExceptions(unittest.TestCase):
    """Each unlocked install needs its own exception with a reason and an exit."""

    def test_unexcepted_pinned_tool_is_rejected(self) -> None:
        violations = install_violations(FIXTURES / "install_good", ())

        self.assertEqual(len(violations), 1)
        self.assertIn("shellcheck-py==0.11.0.1", violations[0].message)
        self.assertEqual(violations[0].rule_id, INSTALL_RULE)

    def test_pinned_tool_category_requires_an_exact_pin(self) -> None:
        unpinned = RuleException(
            path=".github/workflows/ci.yml",
            reason="ruff runs outside the project",
            match="uvx ruff check .",
            category="pinned-tool",
        )

        violations = install_violations(FIXTURES / "install_bad", (unpinned,))

        self.assertIn(
            "not pinned to an exact version",
            " ".join(violation.message for violation in violations),
        )

    def test_exception_without_a_site_is_rejected(self) -> None:
        blanket = RuleException(
            path="Dockerfile", reason="images are special", removal="never"
        )

        messages = [
            violation.message
            for violation in install_violations(FIXTURES / "install_bad", (blanket,))
        ]

        self.assertTrue(any("names no install site" in message for message in messages))

    def test_exception_without_removal_or_tracked_review_is_rejected(self) -> None:
        undated = RuleException(
            path="Dockerfile",
            reason="the image predates uv",
            match="pip install requests",
            expires=date(2099, 1, 1),
        )

        messages = [
            violation.message
            for violation in install_violations(FIXTURES / "install_bad", (undated,))
        ]

        self.assertTrue(
            any("needs a removal condition" in message for message in messages)
        )

    def test_exception_with_removal_condition_covers_its_site(self) -> None:
        excepted = RuleException(
            path="Dockerfile",
            reason="the image predates uv",
            match="pip install requests",
            removal="when the image installs with uv sync --frozen",
        )

        violations = install_violations(FIXTURES / "install_bad", (excepted,))

        self.assertFalse(
            any("Dockerfile" in violation.message for violation in violations)
        )

    def test_stale_exception_is_rejected(self) -> None:
        stale = RuleException(
            path="Dockerfile",
            reason="the image predates uv",
            match="pip install flask",
            removal="when the image installs with uv sync --frozen",
        )

        messages = [
            violation.message
            for violation in install_violations(FIXTURES / "install_good", (stale,))
        ]

        self.assertTrue(
            any("matches no unlocked install" in message for message in messages)
        )

    def test_registry_loads_site_exceptions(self) -> None:
        registry, violations = load_text(
            """
schema_version = 1
repo = "example"
[[category]]
id = "dependencies"
title = "Dependencies"
[[rule]]
id = "example.install"
category = "dependencies"
statement = "Install from uv.lock."
rationale = "docs/dependencies.md"
scope = ["Dockerfile"]
tier = "mechanical"
status = "enforced"
autofix = false
[rule.enforcer]
kind = "none"
[[rule.exception]]
path = "Dockerfile"
match = "pip install requests"
reason = "the image predates uv"
removal = "when the image installs with uv sync --frozen"
"""
        )

        self.assertEqual(violations, [])
        assert registry is not None
        (exception,) = registry.rules[0].exceptions
        self.assertEqual(exception.match, "pip install requests")
        self.assertIsNone(exception.expires)


class TestScanCoverage(unittest.TestCase):
    """The scan reads every file kind that can install Python packages."""

    def test_every_install_source_is_scanned(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        fixture_prefixes = ("scripts/rules/tests/fixtures/", "rules/fixtures/")
        this_module = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
        install_sources = {
            path
            for path in tracked
            if not path.startswith(fixture_prefixes)
            and (
                path.startswith(".github/workflows/")
                or path.endswith((".sh", ".mk"))
                or Path(path).name == "Makefile"
                or (
                    "dockerfile" in Path(path).name.lower()
                    and not path.endswith(".dockerignore")
                )
            )
        }

        modal_images = subprocess.run(
            ["git", "grep", "-l", "-e", "modal.Image", "-e", "Image.debian_slim"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.splitlines()
        install_sources |= {
            path
            for path in modal_images
            if not path.startswith(fixture_prefixes) and path != this_module
        }

        self.assertTrue(install_sources)
        self.assertEqual(install_sources - set(scanned_files(REPO_ROOT)), set())


if __name__ == "__main__":
    unittest.main()
