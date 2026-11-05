"""Tests for scripts/rules/makefile.py and for CI jobs that run make targets."""

from __future__ import annotations

import unittest

from scripts.rules.makefile import make_commands, make_recipes, make_targets_run
from scripts.rules.tests.support import Repo

MAKEFILE = (
    ".PHONY: test quality fix quality-check loop\n"
    "export UV_PYTHON ?= 3.12\n"
    "\n"
    "test:\n"
    "\tpython -m pytest tests/unit --disable-pytest-warnings\n"
    "\n"
    "# The checks, after the fixes.\n"
    "quality: fix\n"
    "\t@echo fixed\n"
    "\t$(MAKE) quality-check\n"
    "\n"
    "fix:\n"
    "\truff format .\n"
    "\n"
    "quality-check:\n"
    "\t# mypy runs in another step\n"
    "\t-ruff check .\n"
    "\tmake loop\n"
    "\n"
    "loop:\n"
    "\t$(MAKE) quality-check\n"
)
# MAKEFILE, with quality-check also type-checking.
MAKEFILE_WITH_MYPY = MAKEFILE.replace("\tmake loop\n", "\tuv run mypy\n\tmake loop\n")


class MakeRecipesTest(unittest.TestCase):
    def test_reads_each_target_s_recipe_commands(self) -> None:
        recipes = make_recipes(MAKEFILE)

        self.assertEqual(recipes["fix"], ([], ["ruff format ."]))
        # Shell comments are left out, and the @ prefix is removed. The -
        # prefix, which makes make ignore the command's failure, is kept.
        self.assertEqual(recipes["quality-check"], ([], ["-ruff check .", "make loop"]))
        self.assertEqual(
            recipes["quality"], (["fix"], ["echo fixed", "$(MAKE) quality-check"])
        )
        self.assertNotIn(".PHONY", recipes)
        self.assertNotIn("export UV_PYTHON ?= 3.12", recipes)


class MakeCommandsTest(unittest.TestCase):
    def test_follows_prerequisites_and_the_make_commands_in_recipes(self) -> None:
        self.assertEqual(
            make_commands(MAKEFILE, ["quality"]),
            [
                "ruff format .",
                "echo fixed",
                "$(MAKE) quality-check",
                "-ruff check .",
                "make loop",
                # loop runs quality-check again, which is already listed.
                "$(MAKE) quality-check",
            ],
        )

    def test_an_unknown_target_runs_nothing(self) -> None:
        self.assertEqual(make_commands(MAKEFILE, ["missing"]), [])


class MakeTargetsRunTest(unittest.TestCase):
    def test_finds_the_targets_a_command_runs(self) -> None:
        self.assertEqual(
            make_targets_run("make quality && make -j2 test VERBOSE=1"),
            ["quality", "test"],
        )
        self.assertEqual(make_targets_run("$(MAKE) quality-check"), ["quality-check"])
        self.assertEqual(make_targets_run("make -C docs html"), ["html"])

    def test_other_words_that_contain_make_are_not_make(self) -> None:
        self.assertEqual(make_targets_run("echo make-believe; cmake build"), [])


class MakeTargetInvocationTest(unittest.TestCase):
    """A job runs a command if a make target it runs does (rule.ci invocations)."""

    def test_a_job_runs_the_commands_of_the_make_targets_it_runs(self) -> None:
        with Repo() as repo:
            repo.edit(
                ".github/workflows/pr.yml", "- run: uv run mypy", "- run: make quality"
            )
            repo.write("Makefile", MAKEFILE_WITH_MYPY)
            messages = repo.messages()

            self.assertFalse(
                any("does not run 'mypy'" in message for message in messages),
                messages,
            )

    def test_a_make_target_without_the_command_does_not_count(self) -> None:
        # MAKEFILE mentions mypy only in a comment.
        with Repo() as repo:
            repo.edit(
                ".github/workflows/pr.yml", "- run: uv run mypy", "- run: make quality"
            )
            repo.write("Makefile", MAKEFILE)
            messages = repo.messages()

            self.assertTrue(
                any(
                    "job 'typecheck' in .github/workflows/pr.yml does not run 'mypy'"
                    in message
                    for message in messages
                ),
                messages,
            )


if __name__ == "__main__":
    unittest.main()
