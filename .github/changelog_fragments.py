"""What a changelog fragment is, for the PR check and the release's version bump.

Rule api.process.changelog-fragment. Every pull request adds a changelog
fragment. After a merge to master, the versioning job in
.github/workflows/push.yml runs .github/bump_version.py, which raises the
version in pyproject.toml from the pending fragments' types, and Towncrier then
builds the fragments into CHANGELOG.md. The PR check
(.github/scripts/check_changelog_fragment.sh) and the version bump both read
fragments through ``FragmentDefinition``, so the check accepts only what the
release reads.

A fragment is a regular file directly in the fragment directory (``directory``
in ``[tool.towncrier]`` in pyproject.toml: changelog.d) named
``<name>.<type>.md``, where:

- ``<name>`` is letters and digits, in groups joined by single dots, hyphens or
  underscores, such as ``4083`` or ``update-policyengine-bundle-6.11.1``;
- ``<type>`` is the ``directory`` of one of the ``[[tool.towncrier.type]]``
  entries: breaking, added, changed, fixed or removed;
- its text, read as UTF-8, is not empty or only whitespace.

``.gitkeep``, which keeps the directory in git once a release has removed every
fragment, is the only other file allowed there. Pull request #4084 added
changelog.d/added/4083.md: the old check counted every file under changelog.d/,
so it passed, and the release, which reads only files directly in changelog.d/,
found no fragment.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

RULE_ID = "api.process.changelog-fragment"
CONFIG_FILE = "pyproject.toml"
CONFIG_TABLE = "[tool.towncrier] in pyproject.toml"
DOCUMENTATION = "docs/engineering/skills/github-prs.md#changelog-fragments"
# Keeps the fragment directory in git once a release has removed every fragment.
KEEP_FILE = ".gitkeep"
FRAGMENT_EXTENSION = "md"
NAME_PATTERN = r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*"
FRAGMENT_NAME = re.compile(NAME_PATTERN)
FRAGMENT_FILE_NAME = re.compile(
    rf"(?P<name>{NAME_PATTERN})\.(?P<type>[^.]+)\.{FRAGMENT_EXTENSION}"
)
TYPE_NAME = re.compile(r"[a-z]+")
BYTE_ORDER_MARK = "﻿"
NAME_TERMS = (
    "<name> is letters and digits, in groups joined by single dots, hyphens or "
    "underscores"
)


class ConfigurationError(Exception):
    """[tool.towncrier] doesn't say where fragments live or which types they have."""


@dataclass(frozen=True)
class Fragment:
    """A changelog fragment the release reads: its path, name and type."""

    path: str
    name: str
    fragment_type: str


@dataclass(frozen=True)
class Scan:
    """What the fragment directory holds: its fragments, and every other file.

    ``problems`` maps each other path, from the repository root, to why the
    release can't read it.
    """

    fragments: tuple[Fragment, ...]
    problems: dict[str, str] = field(default_factory=dict)


def _listed(names: tuple[str, ...]) -> str:
    """Return ``names`` as "a, b or c"."""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} or {names[-1]}"


def _nested_entries(folder: Path) -> list[Path]:
    """Return every file and symbolic link under ``folder``, and each empty folder.

    Symbolic links to folders are returned, not followed.
    """
    children = sorted(folder.iterdir())
    if not children:
        return [folder]
    entries: list[Path] = []
    for child in children:
        if child.is_dir() and not child.is_symlink():
            entries.extend(_nested_entries(child))
        else:
            entries.append(child)
    return entries


def _file_kind_problem(path: str, file: Path) -> str | None:
    """Return why ``file``, at ``path``, is not a regular file, or None."""
    if file.is_symlink():
        return (
            f"{path} is a symbolic link. A fragment is a regular file that holds "
            "its text; replace the link with one."
        )
    if not file.is_file():
        return (
            f"{path} is not a regular file. A fragment is a regular file that "
            "holds its text; replace it with one."
        )
    return None


def _content_problem(path: str, file: Path) -> str | None:
    """Return why ``file``, at ``path``, holds no fragment text, or None."""
    kind_problem = _file_kind_problem(path, file)
    if kind_problem:
        return kind_problem
    try:
        text = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"{path} is not UTF-8 text. Save it as UTF-8."
    if text.removeprefix(BYTE_ORDER_MARK).strip():
        return None
    emptiness = "is empty" if not text else "holds only whitespace"
    return (
        f"{path} {emptiness}. Write a sentence or two in it saying what changed: "
        "Towncrier would publish an empty entry."
    )


@dataclass(frozen=True)
class FragmentDefinition:
    """Where fragments live and which types they may have, from [tool.towncrier]."""

    directory: str
    types: tuple[str, ...]

    @classmethod
    def load(cls, root: Path) -> FragmentDefinition:
        """Read the fragment directory and types from ``root``'s pyproject.toml."""
        config_path = root / CONFIG_FILE
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            towncrier = config["tool"]["towncrier"]
            directory = towncrier["directory"]
            types = tuple(entry["directory"] for entry in towncrier["type"])
        except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
            msg = (
                f"Could not read the fragment directory and types from "
                f"{CONFIG_TABLE} ({config_path}): {error!r}"
            )
            raise ConfigurationError(msg) from error
        if not isinstance(directory, str) or not FRAGMENT_NAME.fullmatch(directory):
            msg = (
                f"{CONFIG_TABLE} names a fragment directory that is not one "
                f"folder: {directory!r}"
            )
            raise ConfigurationError(msg)
        if not types or len(set(types)) != len(types):
            msg = f"{CONFIG_TABLE} must list each fragment type once: {types!r}"
            raise ConfigurationError(msg)
        for fragment_type in types:
            if (
                not isinstance(fragment_type, str)
                or not TYPE_NAME.fullmatch(fragment_type)
                or fragment_type == FRAGMENT_EXTENSION
            ):
                msg = (
                    f'{CONFIG_TABLE} lists the fragment type "{fragment_type}"; a '
                    f"type is lowercase letters, and not "
                    f'"{FRAGMENT_EXTENSION}", the fragment extension.'
                )
                raise ConfigurationError(msg)
        return cls(directory=directory, types=types)

    def listed_types(self) -> str:
        """Return the fragment types as "a, b or c"."""
        return _listed(self.types)

    def form_terms(self) -> str:
        """Return what ``<type>`` and ``<name>`` stand for in a fragment name."""
        return f"<type> is {self.listed_types()}, and {NAME_TERMS}"

    def accepted_form(self) -> str:
        """Return the sentences that say how to add a fragment."""
        return (
            f"Add a file {self.directory}/<name>.<type>.md, directly in "
            f"{self.directory}/, that says in a sentence or two what changed for "
            f"people who use or run the Public API. {self.form_terms()}, such as "
            f"an issue number. See {DOCUMENTATION} (rule {RULE_ID})."
        )

    def _stops_the_release(self) -> str:
        return (
            f"The release reads only files directly in {self.directory}/ and "
            "stops at anything else there."
        )

    def _suggested_name(self, file_name: str) -> str | None:
        """Return the fragment name ``file_name`` was probably meant to have.

        It takes the last dot-separated part that is a type, ignoring case, as
        Towncrier reads a type, and the parts before it as the name.
        """
        parts = file_name.strip().split(".")
        for index in range(len(parts) - 1, 0, -1):
            candidate_type = parts[index].strip().lower()
            if candidate_type in self.types:
                name = ".".join(parts[:index])
                if FRAGMENT_NAME.fullmatch(name):
                    return f"{name}.{candidate_type}.{FRAGMENT_EXTENSION}"
                return None
        return None

    def _moved_path(self, path: PurePosixPath) -> str | None:
        """Return where a fragment filed in a folder belongs, if that is clear.

        ``changelog.d/added/4083.md`` belongs at ``changelog.d/4083.added.md``.
        """
        match = FRAGMENT_FILE_NAME.fullmatch(path.name)
        if match and match.group("type") in self.types:
            return f"{self.directory}/{path.name}"
        folders = path.relative_to(self.directory).parts[:-1]
        name = path.name.removesuffix(f".{FRAGMENT_EXTENSION}")
        if (
            len(folders) == 1
            and folders[0] in self.types
            and FRAGMENT_NAME.fullmatch(name)
        ):
            return f"{self.directory}/{name}.{folders[0]}.{FRAGMENT_EXTENSION}"
        return None

    def _nested_problem(self, path: PurePosixPath) -> str:
        """Return why a file in a folder inside the fragment directory isn't read."""
        problem = (
            f"{path} is in a folder inside {self.directory}/. "
            f"{self._stops_the_release()}"
        )
        moved_path = self._moved_path(path)
        if moved_path:
            return f"{problem} Move it to {moved_path}."
        return (
            f"{problem} Move it to {self.directory}/<name>.<type>.md, where "
            f"{self.form_terms()}, or delete it."
        )

    def _name_problem(self, path: str) -> str | None:
        """Return why ``path`` is not where and how a fragment is named, or None."""
        location = PurePosixPath(path)
        if not location.is_relative_to(self.directory) or location == PurePosixPath(
            self.directory
        ):
            return f"{path} is not in {self.directory}/."
        if location.parent != PurePosixPath(self.directory):
            return self._nested_problem(location)
        match = FRAGMENT_FILE_NAME.fullmatch(location.name)
        if match is None:
            suggested_name = self._suggested_name(location.name)
            fix = (
                f"Rename it to {self.directory}/{suggested_name}."
                if suggested_name
                else (
                    f"Rename it to {self.directory}/<name>.<type>.md, where "
                    f"{self.form_terms()}."
                )
            )
            return (
                f"{path} is not named <name>.<type>.md: its file name is "
                f"{location.name!r}. The release can't read it. {fix}"
            )
        fragment_type = match.group("type")
        if fragment_type in self.types:
            return None
        if fragment_type.lower() in self.types:
            return (
                f'{path} has the type "{fragment_type}", but types are lowercase. '
                f"Rename it to {self.directory}/{match.group('name')}."
                f"{fragment_type.lower()}.{FRAGMENT_EXTENSION}."
            )
        return (
            f'{path} has the type "{fragment_type}", which is not one of the types '
            f"in {CONFIG_TABLE}: {self.listed_types()}. Rename it to "
            f"{self.directory}/{match.group('name')}.<type>.md with one of those "
            "types."
        )

    def problem_with(self, path: str, file: Path) -> str | None:
        """Return why ``file``, at ``path`` from the repository root, isn't a fragment.

        Return None when it is one.
        """
        return (
            _file_kind_problem(path, file)
            or self._name_problem(path)
            or _content_problem(path, file)
        )

    def _fragment(self, path: str) -> Fragment:
        """Return the fragment at ``path``, a name ``problem_with`` accepted."""
        match = FRAGMENT_FILE_NAME.fullmatch(PurePosixPath(path).name)
        if match is None:
            msg = f"{path} is not named <name>.<type>.md"
            raise ValueError(msg)
        return Fragment(
            path=path, name=match.group("name"), fragment_type=match.group("type")
        )

    def _folder_problems(self, root: Path, folder: Path) -> dict[str, str]:
        """Return a problem for each file, link and empty folder under ``folder``."""
        problems = {}
        for entry in _nested_entries(folder):
            path = entry.relative_to(root).as_posix()
            if entry.is_dir() and not entry.is_symlink():
                problems[path] = (
                    f"{path} is an empty folder inside {self.directory}/. "
                    f"{self._stops_the_release()} Delete it."
                )
            else:
                problems[path] = self._nested_problem(PurePosixPath(path))
        return problems

    def scan(self, root: Path) -> Scan:
        """Return the fragments in ``root``'s fragment directory, and every other file.

        Every file, symbolic link and empty folder in a folder inside the
        directory is a problem: Towncrier stops at a folder there.
        """
        directory = root / self.directory
        if not directory.exists() and not directory.is_symlink():
            return Scan(fragments=())
        if directory.is_symlink() or not directory.is_dir():
            return Scan(
                fragments=(),
                problems={
                    self.directory: (
                        f"{self.directory} is not a folder. The release reads "
                        f"fragments from the folder {self.directory}/; make it one."
                    )
                },
            )
        fragments: list[Fragment] = []
        problems: dict[str, str] = {}
        for entry in sorted(directory.iterdir()):
            path = f"{self.directory}/{entry.name}"
            if entry.is_dir() and not entry.is_symlink():
                problems.update(self._folder_problems(root, entry))
                continue
            if entry.name == KEEP_FILE:
                kind_problem = _file_kind_problem(path, entry)
                if kind_problem:
                    problems[path] = kind_problem
                continue
            problem = self.problem_with(path, entry)
            if problem is None:
                fragments.append(self._fragment(path))
            else:
                problems[path] = problem
        return Scan(fragments=tuple(fragments), problems=problems)
