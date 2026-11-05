"""What make targets run: their recipes, prerequisites and recursive make calls.

The rules guard follows a CI job's ``make <target>`` into the Makefile, so a
rule's invocation counts when a target the job runs has it, and the Import
Linter guard checks the commands there too. This reads the subset of make
syntax the repository's Makefile uses: rules with prerequisites, tab-indented
recipes, backslash continuations and comments. Standard library only.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# `targets: prerequisites`, but not a variable assignment such as `A := b`.
_RULE = re.compile(r"^([^\s:=#][^:=#]*?)\s*:(?![=:])(.*)$")
# make, or the $(MAKE) a recipe calls it as, as a word of a shell command.
_MAKE_CALL = re.compile(r"(?:^|(?<=[\s;&|(]))(?:make|\$\(MAKE\)|\$\{MAKE\})(?=\s|$)")
# Where one shell command ends and the next begins.
_COMMAND_END = re.compile(r"[;&|)\n]")
# make options whose value is the next word, which isn't a target.
_OPTIONS_WITH_VALUES = frozenset(
    {"-C", "-f", "-I", "-o", "-W", "--directory", "--file", "--makefile"}
)
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
    Special targets such as ``.PHONY`` are left out.
    """
    recipes: Recipes = {}
    targets: list[str] = []
    for line in _logical_lines(text):
        if line.startswith("\t"):
            command = line.strip().lstrip(_HARMLESS_PREFIXES).strip()
            if command and not command.startswith("#"):
                for target in targets:
                    recipes[target][1].append(command)
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _RULE.match(line)
        if match is None:
            targets = []
            continue
        targets = [name for name in match.group(1).split() if not name.startswith(".")]
        prerequisites = [
            name
            for name in match.group(2).split("#", 1)[0].split(";", 1)[0].split()
            if name != "|"
        ]
        for target in targets:
            recipes.setdefault(target, ([], []))[0].extend(prerequisites)
    return recipes


def make_targets_run(command: str) -> list[str]:
    """Return the targets each ``make`` or ``$(MAKE)`` in a shell command runs."""
    targets = []
    for call in _MAKE_CALL.finditer(command):
        words = _COMMAND_END.split(command[call.end() :], maxsplit=1)[0].split()
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


def job_make_commands(root: Path, run_text: str) -> list[str]:
    """Return the commands the make targets in a job's run text run.

    They come from ``root``'s Makefile; there are none without one.
    """
    makefile = root / "Makefile"
    if not makefile.is_file():
        return []
    targets = [
        target for line in run_text.splitlines() for target in make_targets_run(line)
    ]
    return make_commands(makefile.read_text(encoding="utf-8"), targets)
