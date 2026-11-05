"""Tests for scripts/rules/makefile.py and for CI jobs that run make targets."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.rules.makefile import (
    make_commands,
    make_recipes,
    make_targets_run,
    makefile_problems,
    root_makefile_problems,
)
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

    def test_a_later_recipe_replaces_an_earlier_one(self) -> None:
        # make runs only the last recipe of a target defined twice, and adds
        # up its prerequisites.
        recipes = make_recipes("check: a\n\tmypy\n\ncheck: b\n\truff check .\n")

        self.assertEqual(recipes["check"], (["a", "b"], ["ruff check ."]))

    def test_a_target_specific_variable_is_not_a_prerequisite(self) -> None:
        recipes = make_recipes("check: export BASE ?= master\ncheck:\n\tmypy\n")

        self.assertEqual(recipes["check"], ([], ["mypy"]))


class MakefileProblemsTest(unittest.TestCase):
    def test_reports_what_can_hide_a_failing_command(self) -> None:
        for setting, name in (
            (".IGNORE:\n", ".IGNORE"),
            (".IGNORE: check\n", ".IGNORE"),
            (".ONESHELL:\n", ".ONESHELL"),
            ("MAKEFLAGS += -i\n", "MAKEFLAGS"),
            ("export SHELL := /usr/bin/true\n", "SHELL"),
            ("check: SHELL := /usr/bin/true\n", "SHELL"),
            ("override .SHELLFLAGS = -c\n", ".SHELLFLAGS"),
            (".IGNORE::\n", ".IGNORE"),
            ("GNUMAKEFLAGS += -i\n", "GNUMAKEFLAGS"),
            ("MAKEFILES = ci.mk\n", "MAKEFILES"),
            ("M = MAKE\n$(M)FLAGS += -i\n", "computed"),
            ("I = .IGNORE\n$(I):\n", "computed"),
        ):
            with self.subTest(setting=setting):
                problems = makefile_problems(setting + "check:\n\tmypy\n")

                self.assertTrue(any(name in problem for problem in problems), problems)

    def test_reports_syntax_the_reader_does_not_follow(self) -> None:
        # Each can change what make runs without the reader seeing it, so the
        # reader rejects it rather than guess.
        for setting, name in (
            ("include extra.mk\n", "include"),
            ("-include extra.mk\n", "include"),
            ("ifdef GITHUB_ACTIONS\ncheck:\n\t@true\nendif\n", "ifdef"),
            ("ifeq ($(CI),true)\nendif\n", "ifeq"),
            ("define SKIP\n@true\nendef\n", "define"),
            ("$(eval MAKEFLAGS += -i)\n", "$(eval"),
            ('check: ; @echo "nothing runs"\n', "after ';'"),
        ):
            with self.subTest(setting=setting):
                problems = makefile_problems("check:\n\tmypy\n" + setting)

                self.assertTrue(any(name in problem for problem in problems), problems)

    def test_reports_another_makefile_make_reads_first(self) -> None:
        # GNU make reads GNUmakefile, then makefile, before Makefile.
        for name in ("GNUmakefile", "makefile"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "Makefile").write_text(MAKEFILE)
                (root / name).write_text("quality:\n\t@true\n")
                listed = {path.name for path in root.iterdir()}
                if listed != {"Makefile", name}:
                    # A file system that ignores case keeps one of the two.
                    continue

                problems = root_makefile_problems(root)

                self.assertTrue(any(name in problem for problem in problems), problems)

    def test_ordinary_rules_and_variables_are_fine(self) -> None:
        self.assertEqual(makefile_problems(MAKEFILE), [])


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
        # Another directory's or file's targets aren't the root Makefile's.
        for command in (
            "make -C docs html",
            "make --directory=docs html",
            "make -f other.mk quality",
            "make --file=other.mk quality",
        ):
            with self.subTest(command=command):
                self.assertEqual(make_targets_run(command), [])

    def test_a_call_that_runs_no_command_or_ignores_failures_runs_nothing(
        self,
    ) -> None:
        # -n and its long forms only print the commands, -q and -t run none,
        # and -i ignores their failures.
        for command in (
            "make -n quality",
            "make --dry-run quality",
            "make --just-print quality",
            "make -q quality",
            "make -t quality",
            "make -i quality",
            "make --ignore-errors quality",
            "make -ki quality",
            # GNU make accepts an unambiguous start of a long option.
            "make --dry quality",
            "make --just quality",
            "make --ign quality",
            # These print something and exit.
            "make -v quality",
            "make --version quality",
            "make -h quality",
            "make --help quality",
            # MAKEFLAGS in the command's environment works as the options do.
            "MAKEFLAGS=-i make quality",
            "env MAKEFLAGS=i make quality",
            "GNUMAKEFLAGS=-i make quality",
            "MAKEFILES=ci.mk make quality",
            # -o treats a target as up to date; --eval and -E read more of
            # the Makefile; settings on the command line override it.
            "make -o quality quality",
            "make --old-file=quality quality",
            "make -oquality quality",
            "make --eval=.IGNORE: quality",
            "make -E .IGNORE: quality",
            "make quality SHELL=/bin/true",
            "make quality MAKEFLAGS=-i",
            # make here is an argument, not the command.
            "echo make quality",
        ):
            with self.subTest(command=command):
                self.assertEqual(make_targets_run(command), [])
        # An option's own value isn't read as more options.
        self.assertEqual(make_targets_run("make -Otarget -j4 quality"), ["quality"])

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

    def test_no_target_counts_when_the_makefile_can_hide_a_failure(self) -> None:
        with Repo() as repo:
            repo.edit(
                ".github/workflows/pr.yml", "- run: uv run mypy", "- run: make quality"
            )
            repo.write("Makefile", ".IGNORE: quality-check\n" + MAKEFILE_WITH_MYPY)
            messages = repo.messages()

            self.assertTrue(
                any(
                    "does not run 'mypy'" in message and ".IGNORE" in message
                    for message in messages
                ),
                messages,
            )

    def test_a_command_whose_failure_make_ignores_does_not_count(self) -> None:
        with Repo() as repo:
            repo.edit(
                ".github/workflows/pr.yml", "- run: uv run mypy", "- run: make quality"
            )
            repo.write(
                "Makefile", MAKEFILE.replace("\tmake loop\n", "\t-uv run mypy\n")
            )
            messages = repo.messages()

            self.assertTrue(
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
