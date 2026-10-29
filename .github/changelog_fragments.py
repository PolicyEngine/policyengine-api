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
- its text, read as UTF-8, has at least one visible character: it is not
  empty, only whitespace or only invisible characters such as a zero-width
  space.

``.gitkeep``, which keeps the directory in git once a release has removed every
fragment, is the only other file allowed there. Pull request #4084 added
changelog.d/added/4083.md: the old check counted every file under changelog.d/,
so it passed, and the release, which reads only files directly in changelog.d/,
found no fragment.

Commands, run from the repository root:

  directory           print the fragment directory
  check-pull-request  read ``git diff --find-renames --name-status -z`` output
                      for the fragment directory on stdin, from the pull
                      request's base to the checked-out commit, and exit 1
                      unless the pull request adds a fragment of its own and
                      every file in the directory is a fragment.
                      ``--released-paths FILE`` names the fragments the base
                      branch removed after the pull request's branch left it,
                      NUL-separated, as ``git log --name-only -z`` prints them
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
import unicodedata
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
BYTE_ORDER_MARK = "\ufeff"
# Unicode general category groups a reader can see: letters, marks, numbers,
# punctuation and symbols. Separators (Z) and other characters (C: controls and
# format characters such as a zero-width space or a byte-order mark) aren't.
VISIBLE_CATEGORY_GROUPS = frozenset("LMNPS")
NAME_TERMS = (
    "<name> is letters and digits, in groups joined by single dots, hyphens or "
    "underscores"
)
# git diff --name-status statuses that name two paths: the source, then the
# destination. Every other status names one.
TWO_PATH_STATUSES = frozenset({"R", "C"})
ON_THE_BASE_BRANCH = (
    "It is already on the base branch, so the next release fails until a pull "
    "request fixes it."
)
ALREADY_RELEASED = (
    "is a fragment the base branch has already released: a release removed it "
    "after this branch left the base branch, so merging would publish it again. "
    "This happens when a pull request lower in a stack merged; rebase this "
    "branch onto the base branch without that pull request's commits. If it is "
    "a new note that reuses the name, rename it."
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
class Change:
    """One file a pull request changes, from ``git diff --name-status``.

    ``status`` is git's status letter: A added, C copied, D deleted, M
    modified, R renamed, T changed type. ``source`` is the path a renamed or
    copied file came from.
    """

    status: str
    path: str
    source: str | None = None


@dataclass(frozen=True)
class Scan:
    """What the fragment directory holds: its fragments, and everything else.

    ``problems`` maps each other file and symbolic link, by its path from the
    repository root, to why the release can't read it. ``empty_folders`` lists
    the empty folders, which git can't commit: a checkout has one only when a
    local command left it behind or a submodule is there.
    """

    fragments: tuple[Fragment, ...]
    problems: dict[str, str] = field(default_factory=dict)
    empty_folders: tuple[str, ...] = ()


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
    if any(
        unicodedata.category(character)[0] in VISIBLE_CATEGORY_GROUPS
        for character in text
    ):
        return None
    if not text:
        emptiness = "is empty."
    elif not text.removeprefix(BYTE_ORDER_MARK).strip():
        emptiness = "holds only whitespace."
    else:
        emptiness = (
            "holds no visible text, only invisible characters such as zero-width "
            "spaces."
        )
    return (
        f"{path} {emptiness} Write a sentence or two in it saying what changed: "
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

    def names_a_fragment(self, path: str) -> bool:
        """Return whether ``path`` is where and how a fragment is named.

        This looks only at the path, not at a file's text.
        """
        return self._name_problem(path) is None

    def added_paths(self, changes: list[Change]) -> set[str]:
        """Return the paths a pull request adds a file at, by its ``changes``.

        A renamed file counts only when its old path was not a fragment name:
        renaming a fragment already on the base branch adds no release note,
        but moving a file the release couldn't read into place does.
        """
        added = set()
        for change in changes:
            if change.status in {"A", "C"} or (
                change.status == "R"
                and change.source is not None
                and not self.names_a_fragment(change.source)
            ):
                added.add(change.path)
        return added

    def _fragment(self, path: str) -> Fragment:
        """Return the fragment at ``path``, a name ``problem_with`` accepted."""
        match = FRAGMENT_FILE_NAME.fullmatch(PurePosixPath(path).name)
        if match is None:
            msg = f"{path} is not named <name>.<type>.md"
            raise ValueError(msg)
        return Fragment(
            path=path, name=match.group("name"), fragment_type=match.group("type")
        )

    def empty_folder_problem(self, path: str) -> str:
        """Return why the release can't build with an empty folder at ``path``."""
        return (
            f"{path} is an empty folder or a submodule inside {self.directory}/. "
            f"{self._stops_the_release()} Delete it."
        )

    def scan(self, root: Path) -> Scan:
        """Return the fragments in ``root``'s fragment directory, and every other file.

        Every file and symbolic link in a folder inside the directory is a
        problem: Towncrier stops at a folder there.
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
        empty_folders: list[str] = []
        for entry in sorted(directory.iterdir()):
            path = f"{self.directory}/{entry.name}"
            if entry.is_dir() and not entry.is_symlink():
                for nested_entry in _nested_entries(entry):
                    nested_path = nested_entry.relative_to(root).as_posix()
                    if nested_entry.is_dir() and not nested_entry.is_symlink():
                        empty_folders.append(nested_path)
                    else:
                        problems[nested_path] = self._nested_problem(
                            PurePosixPath(nested_path)
                        )
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
        return Scan(
            fragments=tuple(fragments),
            problems=problems,
            empty_folders=tuple(empty_folders),
        )


def parse_name_status(output: bytes) -> list[Change]:
    """Return the changes in ``git diff --name-status -z`` output.

    Paths that aren't UTF-8 keep their bytes as surrogate escapes, as
    ``os.fsdecode`` decodes them on Linux.
    """
    fields = [
        output_field.decode("utf-8", errors="surrogateescape")
        for output_field in output.split(b"\0")
    ]
    if fields and not fields[-1]:
        fields.pop()
    changes = []
    index = 0
    while index < len(fields):
        status = fields[index][:1]
        path_count = 2 if status in TWO_PATH_STATUSES else 1
        paths = fields[index + 1 : index + 1 + path_count]
        if not status or len(paths) != path_count:
            msg = (
                f"git diff --name-status output ends in the middle of a change: "
                f"{fields[index:]!r}"
            )
            raise ValueError(msg)
        if path_count == 1:
            changes.append(Change(status=status, path=paths[0]))
        else:
            changes.append(Change(status=status, path=paths[1], source=paths[0]))
        index += 1 + path_count
    return changes


def parse_paths(output: bytes) -> set[str]:
    """Return the NUL-separated paths in ``output``, as ``git log -z`` prints them.

    git separates one commit's paths from the next with a newline as well.
    """
    return {
        path.strip(b"\n").decode("utf-8", errors="surrogateescape")
        for path in output.split(b"\0")
        if path.strip(b"\n")
    }


def annotation_message(message: str) -> str:
    """Escape ``message`` so the Actions runner reads it as one annotation message."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotation_property(value: str) -> str:
    """Escape ``value`` for an annotation property such as ``file=``."""
    return annotation_message(value).replace(":", "%3A").replace(",", "%2C")


def _print_error(message: str, path: str | None = None) -> None:
    """Print ``message`` as an error annotation, on ``path`` when one is given."""
    location = f" file={annotation_property(path)}" if path else ""
    print(f"::error{location}::{annotation_message(message)}")


def _no_own_fragment_message(
    definition: FragmentDefinition, scan: Scan, changes: list[Change]
) -> str:
    """Return the error for a pull request that adds no fragment of its own."""
    sentences = ["This pull request adds no changelog fragment of its own."]
    pending = [fragment.path for fragment in scan.fragments]
    if pending:
        sentences.append(
            "Fragments already on the base branch belong to the pull requests "
            f"that added them: {', '.join(pending)}."
        )
    sentences.extend(
        "Renaming a fragment that is already on the base branch "
        f"({change.source} to {change.path}) doesn't add one."
        for change in changes
        if change.status == "R"
        and change.source is not None
        and definition.names_a_fragment(change.source)
    )
    sentences.append(definition.accepted_form())
    return " ".join(sentences)


def check_pull_request(
    root: Path, changes: list[Change], released_paths: set[str] | None = None
) -> int:
    """Check the checkout in ``root`` of a pull request that makes ``changes``.

    ``released_paths`` are the fragments the base branch removed after the pull
    request's branch left it: one the pull request adds back is a problem, not
    a fragment of its own. Print an error annotation for each file in the
    fragment directory that is not a fragment, and one if the pull request
    adds no fragment of its own; return the exit status.
    """
    definition = FragmentDefinition.load(root)
    scan = definition.scan(root)
    changed_paths = {change.path for change in changes if change.status != "D"}
    problems = {
        path: problem if path in changed_paths else f"{problem} {ON_THE_BASE_BRANCH}"
        for path, problem in scan.problems.items()
    }
    # A path the pull request changed that is neither a fragment, the keep
    # file nor a problem holds no file in the checkout: it is a submodule. An
    # empty folder the pull request didn't change was left by a local command,
    # since git can't commit one.
    read_paths = {fragment.path for fragment in scan.fragments} | set(problems)
    keep_path = f"{definition.directory}/{KEEP_FILE}"
    if (root / keep_path).is_file() and not (root / keep_path).is_symlink():
        read_paths.add(keep_path)
    problems.update(
        (path, definition.empty_folder_problem(path))
        for path in sorted(changed_paths - read_paths)
    )
    added_paths = definition.added_paths(changes)
    resurrected_paths = added_paths & (released_paths or set())
    problems.update(
        (path, f"{path} {ALREADY_RELEASED}") for path in sorted(resurrected_paths)
    )
    own_fragments = [
        fragment
        for fragment in scan.fragments
        if fragment.path in added_paths - resurrected_paths
    ]
    for path, problem in problems.items():
        _print_error(problem, path)
    if not own_fragments:
        _print_error(_no_own_fragment_message(definition, scan, changes))
    if problems or not own_fragments:
        return 1

    count = (
        "1 changelog fragment"
        if len(own_fragments) == 1
        else f"{len(own_fragments)} changelog fragments"
    )
    listed = ", ".join(
        f"{fragment.path} ({fragment.fragment_type})" for fragment in own_fragments
    )
    print(f"This pull request adds {count}: {listed}.")
    return 0


def main(arguments: list[str] | None = None) -> int:
    """Run the command named in ``arguments``; return the exit status."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("directory", help="print the fragment directory")
    check_parser = commands.add_parser(
        "check-pull-request",
        help="check a pull request; git diff --name-status -z output on stdin",
    )
    check_parser.add_argument(
        "--released-paths",
        type=Path,
        help="file of fragments the base branch removed since the branch left it",
    )
    options = parser.parse_args(arguments)
    root = Path.cwd()
    try:
        if options.command == "directory":
            print(FragmentDefinition.load(root).directory)
            return 0
        changes = parse_name_status(sys.stdin.buffer.read())
        released_paths = (
            parse_paths(options.released_paths.read_bytes())
            if options.released_paths
            else set()
        )
        return check_pull_request(root, changes, released_paths)
    except (ConfigurationError, ValueError) as error:
        _print_error(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
