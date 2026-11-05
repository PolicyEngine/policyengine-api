"""What make targets run: their recipes, prerequisites and recursive make calls.

The rules guard follows a CI job's ``make <target>`` into the Makefile, so a
rule's invocation counts when a target the job runs has it, and the Import
Linter guard checks the commands there too. This reads the subset of make
syntax the repository's Makefile uses: rules with prerequisites, tab-indented
recipes, target-specific variables, backslash continuations and comments. A
Makefile that can hide a failing command (``makefile_problems``) gets no
credit for its targets' commands. Standard library only.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# `targets: prerequisites`, but not a variable assignment such as `A := b`.
_RULE = re.compile(r"^([^\s:=#][^:=#]*?)\s*:(?![=:])(.*)$")
# A variable assignment, with its optional export or override.
_ASSIGNMENT = re.compile(
    r"^\s*(?:(?:export|override|private)\s+)*([^\s:=#?+!]+)\s*(?::{1,3}=|[?+!]?=)"
)
# Variables whose value can stop a failing command from failing make: -i in
# MAKEFLAGS, or a SHELL or .SHELLFLAGS that doesn't run the command.
_FAILURE_VARIABLES = frozenset({"MAKEFLAGS", "MFLAGS", "SHELL", ".SHELLFLAGS"})
# Special targets that do: .IGNORE ignores errors, and .ONESHELL gives a
# recipe the exit status of its last command only.
_FAILURE_TARGETS = {
    ".IGNORE": "makes make ignore failing commands",
    ".ONESHELL": (
        "runs each recipe in one shell, whose exit status is its last command's"
    ),
}
# Directives that change what make reads or runs in ways this reader doesn't
# follow: other files, conditionals and multi-line variables.
_UNFOLLOWED_DIRECTIVE = re.compile(
    r"^\s*(-?include|sinclude|-?load|ifdef|ifndef|ifeq|ifneq|else|endif|define"
    r"|endef|undefine)(?=\s|$)"
)
# $(eval ...), which makes make read text as more of the Makefile.
_EVAL = re.compile(r"\$[({]\s*eval\b")
# The Makefile names GNU make reads before Makefile.
_EARLIER_MAKEFILES = ("GNUmakefile", "makefile")
# make, or the $(MAKE) a recipe calls it as, as a word of a shell command.
_MAKE_CALL = re.compile(r"(?:^|(?<=[\s;&|(]))(?:make|\$\(MAKE\)|\$\{MAKE\})(?=\s|$)")
# Where one shell command ends and the next begins.
_COMMAND_END = re.compile(r"[;&|)\n]")
# MAKEFLAGS or MFLAGS set in a command's environment, before make.
_FLAGS_PREFIX = re.compile(r"(?:^|\s)M(?:AKE)?FLAGS=")
# Long options after which make runs no recipe, or ignores its failures, or
# only prints something. GNU make also accepts an unambiguous start of one.
_NO_RUN_OPTIONS = (
    "--dry-run",
    "--just-print",
    "--recon",
    "--question",
    "--touch",
    "--ignore-errors",
    "--version",
    "--help",
)
# Short options that do the same: -n, -q, -t, -i, -v and -h.
_NO_RUN_LETTERS = frozenset("nqtivh")
# Long options that read another directory's or file's Makefile.
_OTHER_MAKEFILE_OPTIONS = ("--directory", "--file", "--makefile")
# Short options that do the same: -C and -f.
_OTHER_MAKEFILE_LETTERS = frozenset("Cf")
# Short options whose value follows, in the same word or the next one.
_VALUE_LETTERS = frozenset("IjloOW")
# make options whose value is the next word, which isn't a target.
_OPTIONS_WITH_VALUES = frozenset({"-I", "-o", "-W"})
# Recipe prefixes that change nothing about whether a failure fails make: @
# stops make printing the command, and + runs it under make -n too. The -
# prefix, which ignores the command's failure, is kept.
_HARMLESS_PREFIXES = "@+"

Recipes = dict[str, tuple[list[str], list[str]]]


def _logical_lines(text: str) -> list[str]:
    """Join each line that ends in a backslash with the next one."""
    lines: list[str] = []
    pending = ""
    for line in text.splitlines():
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        lines.append(pending + line)
        pending = ""
    if pending:
        lines.append(pending)
    return lines


def make_recipes(text: str) -> Recipes:
    """Return each target's prerequisites and recipe commands, in order.

    Shell comments are left out, and the ``@`` and ``+`` prefixes removed.
    Special targets such as ``.PHONY`` are left out. As make does, a later
    recipe for a target replaces an earlier one, and prerequisites add up.
    """
    recipes: Recipes = {}
    targets: list[str] = []
    fresh: set[str] = set()
    for line in _logical_lines(text):
        if line.startswith("\t"):
            command = line.strip().lstrip(_HARMLESS_PREFIXES).strip()
            if command and not command.startswith("#"):
                for target in targets:
                    if target in fresh:
                        recipes[target][1].clear()
                        fresh.discard(target)
                    recipes[target][1].append(command)
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _RULE.match(line)
        if match is None:
            targets = []
            continue
        names = [name for name in match.group(1).split() if not name.startswith(".")]
        rest = match.group(2).split("#", 1)[0]
        if _ASSIGNMENT.match(rest):
            # A target-specific variable: no prerequisites, and no recipe.
            targets = []
            continue
        prerequisites = [name for name in rest.split(";", 1)[0].split() if name != "|"]
        for target in names:
            recipes.setdefault(target, ([], []))[0].extend(prerequisites)
        targets = names
        fresh = set(names)
    return recipes


def makefile_problems(text: str) -> list[str]:
    """Return what in a Makefile can let a failing command pass, if anything.

    That is a setting that hides failures, or syntax this reader doesn't
    follow, which could change what make runs without the reader seeing it.
    """
    problems: list[str] = []
    for line in _logical_lines(text):
        if _EVAL.search(line):
            problems.append("uses $(eval ...), which this reader doesn't follow")
        if line.startswith("\t") or line.lstrip().startswith("#"):
            continue
        directive = _UNFOLLOWED_DIRECTIVE.match(line)
        if directive:
            problems.append(
                f"uses '{directive.group(1)}', which this reader doesn't follow"
            )
            continue
        match = _RULE.match(line)
        rest = match.group(2).split("#", 1)[0] if match else line
        assignment = _ASSIGNMENT.match(rest)
        if assignment and assignment.group(1) in _FAILURE_VARIABLES:
            problems.append(
                f"sets {assignment.group(1)}, which can stop a failing command "
                "from failing make"
            )
        if not match:
            continue
        problems += [
            f"sets {name}, which {_FAILURE_TARGETS[name]}"
            for name in match.group(1).split()
            if name in _FAILURE_TARGETS
        ]
        if not assignment and ";" in rest:
            problems.append(
                f"gives {match.group(1).strip()} a recipe after ';', which this "
                "reader doesn't follow"
            )
    return list(dict.fromkeys(problems))


def _credits_no_target(word: str) -> bool:
    """Whether a make option means the root Makefile's targets don't count.

    That is an option after which make runs no recipe, ignores its failures,
    only prints something, or reads another directory's or file's Makefile.
    """
    if word.startswith("--"):
        name = word.split("=", 1)[0]
        return name != "--" and any(
            option.startswith(name)
            for option in (*_NO_RUN_OPTIONS, *_OTHER_MAKEFILE_OPTIONS)
        )
    if not word.startswith("-"):
        return False
    for letter in word[1:]:
        if letter in _NO_RUN_LETTERS or letter in _OTHER_MAKEFILE_LETTERS:
            return True
        if letter in _VALUE_LETTERS:
            return False
    return False


def make_targets_run(command: str) -> list[str]:
    """Return the targets each ``make`` or ``$(MAKE)`` in a shell command runs.

    A call credits no target when it runs no recipe or ignores its failures
    (``-n``, ``-q``, ``-t``, ``-i``, their long forms, or MAKEFLAGS set before
    it), only prints something (``-v``, ``-h``), or reads another Makefile
    (``-C``, ``-f``).
    """
    targets = []
    for call in _MAKE_CALL.finditer(command):
        before = _COMMAND_END.split(command[: call.start()])[-1]
        words = _COMMAND_END.split(command[call.end() :], maxsplit=1)[0].split()
        if _FLAGS_PREFIX.search(before) or any(
            _credits_no_target(word) for word in words
        ):
            continue
        skip_next = False
        for word in words:
            if skip_next:
                skip_next = False
            elif word in _OPTIONS_WITH_VALUES:
                skip_next = True
            elif not word.startswith("-") and "=" not in word:
                targets.append(word)
    return targets


def make_commands(text: str, targets: Iterable[str]) -> list[str]:
    """Return the commands ``make <targets>`` runs with Makefile ``text``, in order.

    Each target's prerequisites come first, then its recipe. After a recipe
    command that runs make, the commands of the targets it runs follow. Each
    target is followed once, so a loop between targets ends.
    """
    recipes = make_recipes(text)
    commands: list[str] = []
    followed: set[str] = set()

    def follow(target: str) -> None:
        if target in followed or target not in recipes:
            return
        followed.add(target)
        prerequisites, recipe = recipes[target]
        for prerequisite in prerequisites:
            follow(prerequisite)
        for command in recipe:
            commands.append(command)
            for inner in make_targets_run(command):
                follow(inner)

    for target in targets:
        follow(target)
    return commands


def job_make_targets(run_text: str) -> list[str]:
    """Return the make targets a job's run text runs."""
    return [
        target for line in run_text.splitlines() for target in make_targets_run(line)
    ]


def root_makefile_problems(root: Path) -> list[str]:
    """Return ``makefile_problems`` for ``root``'s Makefile, if it has one."""
    makefile = root / "Makefile"
    if not makefile.is_file():
        return []
    # Exact names: a file system that ignores case finds makefile as Makefile.
    names = {path.name for path in root.iterdir()}
    return [
        f"has {name} beside it, which GNU make reads instead"
        for name in _EARLIER_MAKEFILES
        if name in names
    ] + makefile_problems(makefile.read_text(encoding="utf-8"))


def job_make_commands(root: Path, run_text: str) -> list[str]:
    """Return the commands the make targets in a job's run text run.

    They come from ``root``'s Makefile. There are none without one, or when
    make could run something else or hide a failing command
    (``root_makefile_problems``).
    """
    makefile = root / "Makefile"
    if not makefile.is_file() or root_makefile_problems(root):
        return []
    return make_commands(
        makefile.read_text(encoding="utf-8"), job_make_targets(run_text)
    )
