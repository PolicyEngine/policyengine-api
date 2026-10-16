"""Where file-level lint exceptions are allowed.

A ruff ``per-file-ignores`` entry switches rules off for whole files, so it is
allowed only for files where that is the norm rather than an exception to it:

- **tests**: files under a ``tests`` or ``authenticated_tests`` directory;
- **CI/CD scripts**: files under ``.github``;
- **command-line scripts**: files under a ``scripts`` directory, or Python
  modules that run as a program through ``if __name__ == "__main__":``.

Everywhere else a kept finding gets an inline suppression with its reason. See
docs/engineering/skills/rules-registry.md#file-level-exceptions.
"""

from __future__ import annotations

import ast
import os
import re
from functools import cache
from pathlib import Path

TEST_DIRECTORIES = frozenset({"tests", "authenticated_tests"})
CI_DIRECTORY = ".github"
SCRIPT_DIRECTORY = "scripts"
LINTED_SUFFIXES = (".py", ".pyi")
# Directories that hold no source of this repository.
SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
    }
)


# One piece of a ruff (globset) pattern: a wildcard, a character class, an
# alternation character, or a run of literal characters.
GLOB_PIECE = re.compile(r"\*\*/|\*\*|\*|\?|\[!?[^\]]*\]|[{},\[]|[^*?\[{},]+")
# As in ruff, "*" and "?" also match "/".
WILDCARDS = {"**/": "(?:.*/)?", "**": ".*", "*": ".*", "?": "."}


def _character_class(piece: str) -> str:
    if piece == "[":
        return re.escape(piece)
    body = piece[1:-1].replace("\\", "\\\\")
    if body.startswith("!"):
        body = "^" + body[1:]
    return f"[{body}]"


def glob_regex(pattern: str) -> re.Pattern[str]:
    """Translate a ruff (globset) file pattern into a regex over relative paths.

    Supports ``**``, ``*``, ``?``, ``[...]`` and ``{a,b}`` alternatives. As in
    ruff, ``*`` and ``?`` also match ``/``, so ``pkg/*.py`` covers
    ``pkg/sub/module.py`` too.
    """
    parts = []
    open_alternations = 0
    for piece in GLOB_PIECE.findall(pattern):
        if piece in WILDCARDS:
            parts.append(WILDCARDS[piece])
        elif piece.startswith("["):
            parts.append(_character_class(piece))
        elif piece == "{":
            parts.append("(?:")
            open_alternations += 1
        elif piece == "}" and open_alternations:
            parts.append(")")
            open_alternations -= 1
        elif piece == "," and open_alternations:
            parts.append("|")
        else:
            parts.append(re.escape(piece))
    return re.compile("".join(parts) + "$")


@cache
def linted_files(root: Path) -> tuple[str, ...]:
    """Return the repository's Python files as sorted root-relative POSIX paths."""
    found = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in SKIPPED_DIRECTORIES
            and (not name.startswith(".") or name == CI_DIRECTORY)
        ]
        found.extend(
            Path(directory, name).relative_to(root).as_posix()
            for name in files
            if name.endswith(LINTED_SUFFIXES)
        )
    return tuple(sorted(found))


def matching_files(root: Path, pattern: str) -> list[str]:
    """Return the files a ruff ``per-file-ignores`` pattern applies to.

    Like ruff, a pattern matches either a file's path or its name.
    """
    regex = glob_regex(pattern)
    return [
        path
        for path in linted_files(root)
        if regex.match(path) or regex.match(path.rsplit("/", 1)[-1])
    ]


def runs_as_program(root: Path, path: str) -> bool:
    """Return whether a module has a top-level ``if __name__ == "__main__":``."""
    try:
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
            and any(
                isinstance(comparator, ast.Constant) and comparator.value == "__main__"
                for comparator in node.test.comparators
            )
        ):
            return True
    return False


def allows_file_level_exceptions(root: Path, path: str) -> bool:
    """Return whether a file is a test, a CI/CD script or a command-line script."""
    directories = path.split("/")[:-1]
    return (
        any(directory in TEST_DIRECTORIES for directory in directories)
        or (bool(directories) and directories[0] == CI_DIRECTORY)
        or SCRIPT_DIRECTORY in directories
        or runs_as_program(root, path)
    )


def out_of_scope_files(root: Path, pattern: str) -> list[str] | None:
    """Return the files a pattern covers that may not take file-level exceptions.

    ``None`` means the pattern can't be checked: it is negated, so it covers
    every file it doesn't name.
    """
    if pattern.startswith("!"):
        return None
    return [
        path
        for path in matching_files(root, pattern)
        if not allows_file_level_exceptions(root, path)
    ]
