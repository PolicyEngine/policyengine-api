"""The declared-dependencies quality guard: deptry's findings, ratcheted.

deptry reads ``[project]`` in pyproject.toml and the imports in policyengine_api,
in the repository's uv.lock environment, and reports:

- DEP001: an import whose top-level module no declared distribution provides;
- DEP002: a declared runtime dependency that the package never imports;
- DEP003: an imported module installed only as another package's dependency;
- DEP004: an import of a module declared only as a development dependency;
- DEP005: a standard-library module declared as a dependency.

A finding fails unless the rule's baseline file lists it, as ``<code> <module>``.
A baseline entry deptry no longer reports fails too, so the baseline only
shrinks. A declared package the application loads by name rather than by import
(a server the start command runs, a database driver named in a connection URL)
is a ``[[rule.exception]]`` with ``category = "not-imported-package"``,
``match`` set to the package's name and ``path`` set to the file that loads it;
it covers only that package's DEP002 finding. ``path`` must be one file's exact
path from the repository root, and not a file that lists every package; the
exception fails once no line in the file other than a whole-line comment names
the package, or once deptry stops reporting it.

Tolerated findings live only in the code-owned baseline and registry. So the
guard also fails when anything else would hide a finding from deptry:

- a ``[tool.deptry]`` table in pyproject.toml other than ``REQUIRED_SETTINGS``;
- a ``[project.optional-dependencies]`` group other than the dev groups, which
  deptry would count as runtime dependencies although Cloud Run installs no
  extras;
- a ``[project].dependencies`` entry with an environment marker, which deptry
  ignores, so a marker that never holds would declare a package uv never
  installs;
- an inline ``# deptry: ignore`` comment in the package;
- a tracked package file deptry didn't scan (an ignore rule lists it: a
  ``.gitignore``, ``.git/info/exclude``, the global git excludes file, or an
  ``.ignore`` file here or in a parent directory), or one it couldn't parse.
  The guard reads the files deptry scanned from its verbose log.

The rule: docs/engineering/skills/dependencies.md. Standard library only; it
runs deptry through ``uv run --frozen --extra dev``, so uv first syncs .venv to
uv.lock, on Python 3.12 unless ``UV_PYTHON`` says otherwise.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from scripts.rules.file_length import baseline_paths
from scripts.rules.load import load_registry
from scripts.rules.model import RuleException, Violation

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
RULE_ID = "api.dependencies.declared-and-used"
CHECK_NAME = "declared-dependencies"
PACKAGE = "policyengine_api"
NOT_IMPORTED = "not-imported-package"
UNUSED = "DEP002"
DEV_GROUPS = ["dev"]
REQUIRED_SETTINGS = {
    "known_first_party": [PACKAGE],
    "optional_dependencies_dev_groups": DEV_GROUPS,
}
# deptry skips an import on a line with this comment (``# deptry: ignore`` or
# ``# deptry: ignore[DEP001,DEP003]``).
INLINE_IGNORE = re.compile(r"#\s*deptry\s*:\s*ignore", re.IGNORECASE)
SCANNED_SUFFIXES = (".py", ".ipynb")
# Files that list every declared package, so naming a package there shows
# nothing about whether the application loads it.
DECLARATION_FILES = frozenset(
    {"pyproject.toml", "uv.lock", "rules/registry.toml", "docs/generated/rules.md"}
)
GLOB_CHARACTERS = frozenset("*?[")
# deptry's verbose log lists the files it scans after this line, one per line,
# and ends the list with a blank line.
SCANNED_FILES_HEADING = "Python files to scan for imports:"
UNPARSED_FILE = re.compile(
    r"^Warning: Skipping processing of (?P<path>.+?) because of the following error:",
    re.MULTILINE,
)
_HIDDEN_FIX = (
    "remove it; tolerate a finding in the rule's baseline, or as a "
    "not-imported-package exception in rules/registry.toml"
)
# uv runs deptry on the Cloud Run image's Python, as the Makefile and CI jobs
# do, unless UV_PYTHON says otherwise. Without it, uv would follow
# .python-version and rebuild .venv on another Python.
DEFAULT_UV_PYTHON = "3.12"
DEPTRY_TIMEOUT_SECONDS = 600
STDERR_TAIL_LINES = 20

_DECLARE_FIX = (
    "declare the distribution that provides it in [project].dependencies in "
    "pyproject.toml and run uv lock, or remove the import"
)
_UNUSED_FIX = (
    "remove it from [project].dependencies in pyproject.toml and run uv lock, "
    "or move it to the dev extra if only tests use it. A package the "
    "application loads by name rather than by import (a server command, a "
    "database driver in a connection URL) is a [[rule.exception]] on "
    f'{RULE_ID} with category = "{NOT_IMPORTED}", match = the package\'s name '
    "and path = the file that loads it"
)
_TRANSITIVE_FIX = (
    "declare its distribution in [project].dependencies in pyproject.toml and "
    "run uv lock"
)
_DEV_ONLY_FIX = (
    "move it to [project].dependencies in pyproject.toml and run uv lock, or "
    f"stop importing it from {PACKAGE}"
)
_SKIPPED_FILE_FIX = (
    "find the rule that hides it (git check-ignore -v --no-index <path>, or an "
    ".ignore file in its directory or a parent directory) and remove it"
)
_STANDARD_LIBRARY_FIX = "remove it from pyproject.toml and run uv lock"
_UNKNOWN_FIX = "see https://deptry.com/rules-violations/ for what the code means"


class DeptryUnavailableError(Exception):
    """deptry could not run, or ran without writing its report and file list."""


@dataclass(frozen=True)
class Finding:
    """One problem deptry reported, at one place."""

    code: str
    module: str
    file: str
    line: int | None
    message: str

    @property
    def entry(self) -> str:
        """The finding as a baseline entry: ``<code> <module>``."""
        return f"{self.code} {self.module}"

    @property
    def location(self) -> str:
        """``file:line``, or just the file when deptry gives no line."""
        return self.file if self.line is None else f"{self.file}:{self.line}"


def _deptry_command(output: Path) -> list[str]:
    uv = shutil.which("uv")
    if uv is None:
        msg = "uv is not installed, so deptry cannot run in the uv.lock environment"
        raise DeptryUnavailableError(msg)
    return [
        uv,
        "run",
        "--frozen",
        "--extra",
        "dev",
        "--project",
        str(REPO_ROOT),
        "deptry",
        PACKAGE,
        # The verbose log lists the files deptry scanned and those it skipped.
        "--verbose",
        "--json-output",
        str(output),
    ]


def _stderr_tail(stderr: str) -> str:
    return "\n".join(stderr.strip().splitlines()[-STDERR_TAIL_LINES:])


def _parse_report(report: object) -> list[Finding]:
    if not isinstance(report, list):
        msg = "deptry's JSON report is not a list"
        raise DeptryUnavailableError(msg)
    findings = []
    for item in report:
        try:
            findings.append(
                Finding(
                    code=item["error"]["code"],
                    module=item["module"],
                    file=item["location"]["file"],
                    line=item["location"]["line"],
                    message=item["error"]["message"],
                )
            )
        except (KeyError, TypeError) as error:
            msg = f"deptry's JSON report has an unexpected entry: {item!r}"
            raise DeptryUnavailableError(msg) from error
    return findings


def scanned_files_from_log(log: str) -> frozenset[str]:
    """Return the files deptry's verbose log says it scanned for imports.

    Raise DeptryUnavailableError when the log has no such list.
    """
    lines = log.splitlines()
    if SCANNED_FILES_HEADING not in lines:
        msg = "deptry's verbose log doesn't list the files it scanned"
        raise DeptryUnavailableError(msg)
    start = lines.index(SCANNED_FILES_HEADING) + 1
    scanned = []
    for line in lines[start:]:
        if not line.strip():
            break
        scanned.append(Path(line.strip()).as_posix())
    return frozenset(scanned)


@dataclass(frozen=True)
class DeptryRun:
    """What one deptry run reported, and which files it read."""

    findings: list[Finding]
    scanned_files: frozenset[str]
    unparsed_files: tuple[str, ...]


def run_deptry(root: Path) -> DeptryRun:
    """Run deptry on ``root``'s policyengine_api and return what it reports.

    deptry reads ``root``'s pyproject.toml and runs in this repository's
    uv.lock environment, which has every package a proof fixture imports.
    Raise DeptryUnavailableError when it cannot run, writes no report, or its
    log doesn't list the files it scanned.
    """
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "deptry.json"
        environment = {**os.environ}
        environment.setdefault("UV_PYTHON", DEFAULT_UV_PYTHON)
        try:
            completed = subprocess.run(
                _deptry_command(output),
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=DEPTRY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            msg = f"deptry did not finish within {DEPTRY_TIMEOUT_SECONDS} seconds"
            raise DeptryUnavailableError(msg) from error
        if not output.is_file():
            msg = (
                f"deptry exited with {completed.returncode} without writing its "
                f"report:\n{_stderr_tail(completed.stderr)}"
            )
            raise DeptryUnavailableError(msg)
        try:
            report = json.loads(output.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            msg = f"deptry's JSON report doesn't parse: {error}"
            raise DeptryUnavailableError(msg) from error
    unparsed = sorted(
        Path(match.group("path")).as_posix()
        for match in UNPARSED_FILE.finditer(completed.stderr)
    )
    return DeptryRun(
        findings=_parse_report(report),
        scanned_files=scanned_files_from_log(completed.stderr),
        unparsed_files=tuple(unparsed),
    )


def settings_violations(root: Path) -> list[Violation]:
    """Report pyproject.toml settings that would change what deptry reports.

    ``[tool.deptry]`` must equal ``REQUIRED_SETTINGS``, and every
    ``[project.optional-dependencies]`` group must be a dev group.
    """
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    settings = pyproject.get("tool", {}).get("deptry", {})
    fix = (
        f"set [tool.deptry] in pyproject.toml to exactly {REQUIRED_SETTINGS}; "
        f"tolerate a finding in the rule's baseline, or as a {NOT_IMPORTED} "
        "exception in rules/registry.toml, not in a deptry setting"
    )
    violations = []
    for key, required in REQUIRED_SETTINGS.items():
        if key not in settings:
            message = f"pyproject.toml's [tool.deptry] doesn't set {key}"
        elif settings[key] != required:
            message = (
                f"pyproject.toml's [tool.deptry] sets {key} to {settings[key]}, "
                f"not {required}"
            )
        else:
            continue
        violations.append(Violation(RULE_ID, CHECK_NAME, message, fix))
    violations.extend(
        Violation(
            RULE_ID, CHECK_NAME, f"pyproject.toml's [tool.deptry] sets {key}", fix
        )
        for key in sorted(set(settings) - set(REQUIRED_SETTINGS))
    )
    violations.extend(
        Violation(
            RULE_ID,
            CHECK_NAME,
            f"pyproject.toml declares {requirement} with an environment marker, "
            "which deptry ignores",
            "remove the marker: the Cloud Run image runs on one Python and "
            "platform, and a marker that never holds there would declare a "
            "package uv never installs",
        )
        for requirement in pyproject.get("project", {}).get("dependencies", [])
        if ";" in requirement
    )
    extras = pyproject.get("project", {}).get("optional-dependencies", {})
    violations.extend(
        Violation(
            RULE_ID,
            CHECK_NAME,
            "pyproject.toml's [project.optional-dependencies] has the group "
            f"{group}, which deptry counts as runtime dependencies",
            "the Cloud Run image installs no extras (uv sync --frozen --no-dev in "
            "gcp/cloud_run/Dockerfile), so declare a runtime dependency in "
            "[project].dependencies; a group of development tools goes in "
            "DEV_GROUPS in scripts/rules/declared_dependencies.py and in "
            "optional_dependencies_dev_groups under [tool.deptry] in "
            "pyproject.toml",
        )
        for group in sorted(set(extras) - set(DEV_GROUPS))
    )
    return violations


def _package_files(root: Path) -> list[Path]:
    """Return the files under ``root``'s package that deptry scans for imports."""
    package = root / PACKAGE
    return sorted(
        path
        for path in package.rglob("*")
        if path.is_file() and path.suffix in SCANNED_SUFFIXES
    )


def inline_ignore_violations(root: Path) -> list[Violation]:
    """Report every inline ``# deptry: ignore`` comment in the package."""
    violations = []
    for path in _package_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        violations.extend(
            Violation(
                RULE_ID,
                CHECK_NAME,
                f"{path.relative_to(root).as_posix()}:{number} has a deptry ignore "
                "comment",
                _HIDDEN_FIX,
            )
            for number, line in enumerate(text.splitlines(), start=1)
            if INLINE_IGNORE.search(line)
        )
    return violations


def _tracked_package_files(root: Path) -> list[str]:
    """Return the package's tracked files that deptry should scan.

    A directory that isn't a git checkout (a proof fixture, a test's temporary
    tree) has every such file under the package counted.
    """
    if not (root / ".git").exists():
        return [path.relative_to(root).as_posix() for path in _package_files(root)]
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", PACKAGE],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    return sorted(
        path
        for path in listed
        if path.endswith(SCANNED_SUFFIXES) and (root / path).is_file()
    )


def unscanned_file_violations(root: Path, scanned: Iterable[str]) -> list[Violation]:
    """Report tracked package files that deptry didn't scan.

    deptry's file walker skips what ``.gitignore``, ``.git/info/exclude``, the
    global git excludes file and ``.ignore`` files list. An untracked file
    deptry scanned or skipped is not reported.
    """
    scanned = set(scanned)
    return [
        Violation(
            RULE_ID,
            CHECK_NAME,
            f"{path} is tracked, but deptry didn't scan it, so its imports aren't "
            "checked",
            _SKIPPED_FILE_FIX.replace("<path>", path),
        )
        for path in _tracked_package_files(root)
        if path not in scanned
    ]


def unparsed_file_violations(run: DeptryRun) -> list[Violation]:
    """Report the files deptry skipped because it couldn't parse them."""
    return [
        Violation(
            RULE_ID,
            CHECK_NAME,
            f"deptry couldn't parse {path}, so it didn't check that file's imports",
            f"fix the error deptry reports for it (deptry {PACKAGE} prints it)",
        )
        for path in run.unparsed_files
    ]


def _where(findings: Sequence[Finding]) -> str:
    first = findings[0].location
    others = len(findings) - 1
    if others == 0:
        return first
    places = "place" if others == 1 else "places"
    return f"{first} and {others} other {places}"


def _finding_violation(findings: Sequence[Finding]) -> Violation:
    """Describe one ``<code> <module>`` finding, wherever deptry found it."""
    finding = findings[0]
    module = finding.module
    descriptions = {
        "DEP001": (
            f"{module} is imported in {_where(findings)}, but no declared "
            "dependency provides it",
            _DECLARE_FIX,
        ),
        "DEP002": (
            f"{module} is declared in pyproject.toml, but {PACKAGE} never imports it",
            _UNUSED_FIX,
        ),
        "DEP003": (
            f"{module} is imported in {_where(findings)}, but is installed only "
            "as a dependency of another package",
            _TRANSITIVE_FIX,
        ),
        "DEP004": (
            f"{module} is imported in {_where(findings)}, but is declared only "
            "as a development dependency",
            _DEV_ONLY_FIX,
        ),
        "DEP005": (
            f"{module} is declared in pyproject.toml, but is part of the "
            "standard library",
            _STANDARD_LIBRARY_FIX,
        ),
    }
    message, fix = descriptions.get(
        finding.code, (f"{finding.code}: {finding.message}", _UNKNOWN_FIX)
    )
    return Violation(RULE_ID, CHECK_NAME, message, fix)


def _exception_problems(root: Path, exception: RuleException) -> list[str]:
    """Return what makes ``exception`` unusable; empty when it can cover a finding."""
    where = f"exception for {exception.path}"
    problems = []
    if exception.match is None:
        problems.append(f"{where} has no match naming the package")
    if exception.category != NOT_IMPORTED:
        category = None if exception.category is None else repr(exception.category)
        problems.append(
            f"{where} has category {category}; this rule allows only '{NOT_IMPORTED}'"
        )
    if problems or exception.match is None:
        return problems
    path = PurePosixPath(exception.path)
    if (
        GLOB_CHARACTERS & set(exception.path)
        or path.is_absolute()
        or path.as_posix() != exception.path
        or any(part in {".", ".."} for part in exception.path.split("/"))
    ):
        return [
            f"{where} must name one file by its exact path from the repository root"
        ]
    if exception.path in DECLARATION_FILES:
        return [
            f"{where} names a file that lists every declared package, so it "
            "can't show that the application loads one"
        ]
    file = root / exception.path
    if not file.is_file():
        return [f"{where}: the file doesn't exist"]
    if not any(
        exception.match in line
        for line in file.read_text(encoding="utf-8", errors="replace").splitlines()
        if not line.lstrip().startswith("#")
    ):
        problems.append(f"{where}: no line of code in the file names {exception.match}")
    return problems


def _exception_fix(exception: RuleException) -> str:
    return (
        f"correct or remove the [[rule.exception]] for {exception.path} on "
        f"{RULE_ID} in rules/registry.toml"
    )


def compare(
    root: Path,
    findings: Iterable[Finding],
    baseline: set[str],
    baseline_file: str | None,
    exceptions: Iterable[RuleException],
) -> list[Violation]:
    """Report findings no baseline entry or exception covers, and stale entries.

    ``root`` is where exception paths are read from.
    """
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        grouped[finding.entry].append(finding)

    violations: list[Violation] = []
    covered: set[str] = set()
    exception_violations = []
    for exception in exceptions:
        problems = _exception_problems(root, exception)
        if not problems and f"{UNUSED} {exception.match}" not in grouped:
            problems.append(
                f"exception for {exception.path} no longer applies: deptry "
                f"doesn't report {exception.match} as unused"
            )
        if not problems:
            covered.add(f"{UNUSED} {exception.match}")
        exception_violations.extend(
            Violation(RULE_ID, CHECK_NAME, problem, _exception_fix(exception))
            for problem in problems
        )

    violations.extend(
        _finding_violation(grouped[entry])
        for entry in sorted(grouped)
        if entry not in baseline and entry not in covered
    )
    violations.extend(
        Violation(
            RULE_ID,
            CHECK_NAME,
            f"baseline entry no longer applies: {entry}",
            f"remove it from {baseline_file} and lower the rule's baseline count",
        )
        for entry in sorted(baseline - set(grouped))
    )
    violations.extend(exception_violations)
    return violations


def run_check(root: Path = REPO_ROOT) -> list[Violation]:
    """Load the rule from the registry under ``root`` and run deptry on it."""
    registry, violations = load_registry(root)
    if registry is None:
        return violations
    rule = registry.rule(RULE_ID)
    if rule is None:
        return [
            Violation(
                None,
                CHECK_NAME,
                f"rules/registry.toml has no rule {RULE_ID}",
                "register the rule",
            )
        ]
    violations = [*settings_violations(root), *inline_ignore_violations(root)]
    try:
        run = run_deptry(root)
    except DeptryUnavailableError as error:
        return [
            *violations,
            Violation(
                RULE_ID,
                CHECK_NAME,
                f"deptry did not run: {error}",
                "install uv and the locked environment (make install), then "
                "run python scripts/run_quality_guards.py again",
            ),
        ]
    baseline_file = rule.baseline.file if rule.baseline is not None else None
    return [
        *violations,
        *unscanned_file_violations(root, run.scanned_files),
        *unparsed_file_violations(run),
        *compare(
            root,
            run.findings,
            baseline_paths(root, baseline_file),
            baseline_file,
            rule.exceptions,
        ),
    ]


def check() -> list[str]:
    """Adapter for scripts/run_quality_guards.py."""
    return [str(violation) for violation in run_check(REPO_ROOT)]
