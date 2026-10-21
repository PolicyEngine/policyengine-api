"""Find Python package installs that bypass uv.lock.

The Cloud Run image installs exactly the versions in uv.lock
(``uv sync --frozen`` in gcp/cloud_run/Dockerfile). Any other install of the
project's dependencies should do the same, so that CI, scripts and images run
the versions production runs. This guard scans every file kind that can install
Python packages: workflow ``run:`` blocks, shell scripts, Makefiles,
Dockerfiles and Python modules that define Modal images. It reports each
install that does not install from uv.lock and is not a registered exception
in rules/registry.toml.

The rules: docs/engineering/skills/dependencies.md. Standard library only.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.rules.load import load_registry
from scripts.rules.model import RuleException, Violation
from scripts.rules.workflows import parse_jobs

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_RULE = "api.dependencies.install-from-lock"
PINNED_TOOL = "pinned-tool"
# Proof fixtures hold deliberate violations; they are scanned by their tests.
EXCLUDED_PREFIXES = ("scripts/rules/tests/fixtures/",)
WORKFLOW_DIRECTORIES = (".github/workflows/",)
MAKEFILE_NAMES = {"Makefile", "GNUmakefile", "makefile"}

_CONTINUATION = re.compile(r"[ \t]*\\\n\s*")
_COMMAND_SEPARATOR = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
_LOCK_FLAG = re.compile(r"(?:^|\s)--(?:frozen|locked)\b")
_EXTRA_PACKAGES_FLAG = re.compile(r"(?:^|\s)--(?:with|with-requirements|no-project)\b")
_NO_SYNC_FLAG = re.compile(r"(?:^|\s)--no-sync\b")
_UV_PIP = re.compile(r"\buv\s+pip\s+(?:install|sync)\b")
_UV_SYNC = re.compile(r"\buv\s+sync\b")
_UV_RUN = re.compile(r"\buv\s+run\b")
_TOOL_INSTALL = re.compile(
    r"(?:^|\s)uvx\s|\buv\s+tool\s+(?:install|run|upgrade)\b"
    r"|\bpipx\s+(?:install|run|inject)\b"
)
_PIP_INSTALL = re.compile(r"\bpip3?\s+install\b")
_OTHER_INSTALL = re.compile(
    r"\buv\s+add\b|\bpoetry\s+(?:install|add)\b|\b(?:conda|mamba|micromamba)\s+install\b"
    r"|\beasy_install\b|\bsetup\.py\s+(?:install|develop)\b|\bpip-sync\b"
)
_MODAL_CALL = re.compile(
    r"\.(?P<method>pip_install_from_requirements|pip_install_from_pyproject"
    r"|pip_install|uv_pip_install|uv_sync|poetry_install_from_file"
    r"|conda_install|micromamba_install|run_commands)\("
)
_STRING_LITERAL = re.compile(
    r"""(?P<quote>["'])(?P<text>(?:\\.|(?!(?P=quote)).)*)(?P=quote)"""
)
_PYTHON_INSTALLER_CALL = re.compile(
    r"""["'](?:uv|uvx|pipx|pip3?)["']\s*,\s*["'](?:sync|run|pip|tool|add|install)["']"""
    r"""|["']-m["']\s*,\s*["']pip["']"""
)


@dataclass(frozen=True)
class Site:
    """One command or call in a scanned file that installs Python packages."""

    path: str
    command: str
    locked: bool
    pinned: bool


def _tracked_files(root: Path) -> list[str]:
    """Return the repository's tracked files, or every file under a fixture root."""
    if (root / ".git").exists():
        listed = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        return [path for path in listed if (root / path).is_file()]
    return sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )


def _file_kind(path: str) -> str | None:
    name = Path(path).name
    if path.startswith(WORKFLOW_DIRECTORIES) and name.endswith((".yml", ".yaml")):
        return "workflow"
    if path.startswith(".github/actions/") and name in {"action.yml", "action.yaml"}:
        return "workflow"
    if name.endswith(".sh"):
        return "shell"
    if name in MAKEFILE_NAMES or name.endswith(".mk"):
        return "makefile"
    if "dockerfile" in name.lower() and not name.endswith(".dockerignore"):
        return "dockerfile"
    if name.endswith(".py") and "tests" not in Path(path).parts:
        return "python"
    return None


def scanned_files(root: Path = REPO_ROOT) -> dict[str, str]:
    """Return every file the guard scans, mapped to its kind."""
    scanned = {}
    for path in _tracked_files(root):
        if path.startswith(EXCLUDED_PREFIXES):
            continue
        kind = _file_kind(path)
        if kind is not None:
            scanned[path] = kind
    return scanned


def _logical_lines(text: str) -> Iterator[str]:
    """Yield each command line with continuations joined and comments dropped."""
    for raw_line in _CONTINUATION.sub(" ", text).splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#"):
            yield stripped


def _commands(text: str) -> Iterator[str]:
    for logical_line in _logical_lines(text):
        for command in _COMMAND_SEPARATOR.split(logical_line):
            if command:
                yield command


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _requirements_after(tokens: list[str], verb: str) -> list[str] | None:
    """Return the packages named after ``verb``; None when a file names them."""
    if verb not in tokens:
        return []
    arguments = tokens[tokens.index(verb) + 1 :]
    if any(
        argument in {"-e", "-r", "--editable", "--requirement"}
        for argument in arguments
    ):
        return None
    return [argument for argument in arguments if not argument.startswith("-")]


def _with_requirements(tokens: list[str]) -> list[str]:
    return [
        tokens[position + 1]
        for position, option in enumerate(tokens[:-1])
        if option == "--with"
    ]


def _pinned(command: str) -> bool:
    """Whether every package the command installs is pinned to an exact version."""
    tokens = _tokens(command)
    if _UV_RUN.search(command):
        requirements: list[str] | None = _with_requirements(tokens)
    elif "uvx" in tokens or "run" in tokens:
        tool_arguments = tokens[tokens.index("uvx" if "uvx" in tokens else "run") + 1 :]
        requirements = [
            argument for argument in tool_arguments if not argument.startswith("-")
        ][:1]
    else:
        requirements = _requirements_after(tokens, "install")
    return bool(requirements) and all(
        "==" in requirement for requirement in requirements or ()
    )


def classify_command(command: str) -> tuple[bool, bool] | None:
    """Return ``(locked, pinned)`` for a command that installs packages, else None."""
    if _UV_PIP.search(command):
        return False, _pinned(command)
    if _UV_SYNC.search(command):
        return bool(_LOCK_FLAG.search(command)), False
    if _UV_RUN.search(command):
        if _EXTRA_PACKAGES_FLAG.search(command):
            return False, _pinned(command)
        if _NO_SYNC_FLAG.search(command):
            return None
        return bool(_LOCK_FLAG.search(command)), False
    if _TOOL_INSTALL.search(command) or _PIP_INSTALL.search(command):
        return False, _pinned(command)
    if _OTHER_INSTALL.search(command):
        return False, False
    return None


def _call_arguments(text: str, open_paren: int) -> str:
    """Return the text between the parenthesis at ``open_paren`` and its match."""
    depth = 0
    for position in range(open_paren, len(text)):
        if text[position] == "(":
            depth += 1
        elif text[position] == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : position]
    return text[open_paren + 1 :]


def _python_sites(path: str, text: str) -> Iterator[Site]:
    """Yield Modal image install calls and installer subprocess calls."""
    for call in _MODAL_CALL.finditer(text):
        method = call.group("method")
        arguments = _call_arguments(text, call.end() - 1)
        literals = [
            match.group("text") for match in _STRING_LITERAL.finditer(arguments)
        ]
        if method == "run_commands":
            for literal in literals:
                yield from _shell_sites(path, literal)
            continue
        label = f".{method}({' '.join(arguments.split())})"
        if method == "uv_sync":
            locked = re.search(r"\bfrozen\s*=\s*True\b", arguments) is not None
            yield Site(path, label, locked=locked, pinned=False)
            continue
        pinned = (
            method == "pip_install"
            and bool(literals)
            and all("==" in literal for literal in literals)
        )
        yield Site(path, label, locked=False, pinned=pinned)
    for source_line in text.splitlines():
        if _PYTHON_INSTALLER_CALL.search(source_line):
            command = " ".join(
                match.group("text") for match in _STRING_LITERAL.finditer(source_line)
            )
            classified = classify_command(command)
            if classified is not None:
                yield Site(path, command, *classified)


def _shell_sites(path: str, text: str) -> Iterator[Site]:
    for command in _commands(text):
        classified = classify_command(command)
        if classified is not None:
            yield Site(path, command, *classified)


def _workflow_sites(path: str, text: str) -> Iterator[Site]:
    jobs, _ = parse_jobs(text)
    for job in jobs.values():
        for run_block in job.run_blocks:
            yield from _shell_sites(path, run_block.text)


def _makefile_sites(path: str, text: str) -> Iterator[Site]:
    recipe_text = "\n".join(
        makefile_line
        for makefile_line in _CONTINUATION.sub(" ", text).splitlines()
        if makefile_line.startswith("\t")
    )
    yield from _shell_sites(path, recipe_text)


_SITE_FINDERS = {
    "workflow": _workflow_sites,
    "shell": _shell_sites,
    "makefile": _makefile_sites,
    "dockerfile": _shell_sites,
    "python": _python_sites,
}


def install_sites(root: Path = REPO_ROOT) -> list[Site]:
    """Return every install site in the scanned files."""
    sites = []
    for path, kind in sorted(scanned_files(root).items()):
        text = (root / path).read_text(encoding="utf-8", errors="replace")
        sites += _SITE_FINDERS[kind](path, text)
    return sites


def unlocked_install_sites(root: Path = REPO_ROOT) -> list[Site]:
    """Return every install site that does not install exactly what uv.lock pins."""
    return [site for site in install_sites(root) if not site.locked]


def _matches(exception: RuleException, site: Site) -> bool:
    return (
        exception.match is not None
        and Path(site.path).match(exception.path)
        and site.path.count("/") == exception.path.count("/")
        and exception.match in site.command
    )


def _exception_problems(rule_id: str, exception: RuleException) -> Iterator[Violation]:
    where = f"exception for {exception.path}"
    if exception.match is None:
        yield Violation(
            rule_id,
            "locked-installs",
            f"{where} names no install site",
            "set match to text from the one command or call it covers",
        )
    if exception.category not in {None, PINNED_TOOL}:
        yield Violation(
            rule_id,
            "locked-installs",
            f"{where} has unknown category '{exception.category}'",
            f"use category = '{PINNED_TOOL}' or no category",
        )
    tracked_review = exception.expires is not None and exception.issue is not None
    if exception.category is None and exception.removal is None and not tracked_review:
        yield Violation(
            rule_id,
            "locked-installs",
            f"{where} needs a removal condition, or a review date with a tracking "
            "issue",
            "set removal, or set both expires and issue",
        )


def exception_violations(
    rule_id: str, sites: Iterable[Site], exceptions: Iterable[RuleException]
) -> list[Violation]:
    """Report sites no exception covers, and exceptions that are malformed or stale."""
    sites = list(sites)
    exceptions = list(exceptions)
    violations = []
    for exception in exceptions:
        violations += _exception_problems(rule_id, exception)
        covered = [site for site in sites if _matches(exception, site)]
        if exception.match is not None and not covered:
            violations.append(
                Violation(
                    rule_id,
                    "locked-installs",
                    f"exception for {exception.path} ('{exception.match}') "
                    "matches no unlocked install",
                    "remove the stale exception",
                )
            )
        if exception.category == PINNED_TOOL:
            violations += [
                Violation(
                    rule_id,
                    "locked-installs",
                    f"{site.path}: '{site.command}' is not pinned to an exact version",
                    "pin every package with ==, or register an exception "
                    "with a removal condition",
                )
                for site in covered
                if not site.pinned
            ]
    for site in sites:
        if not any(_matches(exception, site) for exception in exceptions):
            violations.append(
                Violation(
                    rule_id,
                    "locked-installs",
                    f"{site.path}: '{site.command}' installs packages outside uv.lock",
                    "install with uv sync --frozen or run with uv run --frozen; "
                    "if locking is not possible, register a [[rule.exception]] "
                    "(docs/engineering/skills/dependencies.md#exceptions)",
                )
            )
    return violations


def install_violations(
    root: Path, exceptions: Iterable[RuleException]
) -> list[Violation]:
    """Report unlocked installs under ``root`` that ``exceptions`` do not cover."""
    return exception_violations(INSTALL_RULE, unlocked_install_sites(root), exceptions)


def run_check(root: Path = REPO_ROOT) -> list[Violation]:
    """Load the registry and return every locked-installs violation."""
    registry, violations = load_registry(root)
    if registry is None:
        return violations
    install_rule = registry.rule(INSTALL_RULE)
    if install_rule is None:
        return [
            Violation(
                None,
                "locked-installs",
                f"rules/registry.toml has no rule {INSTALL_RULE}",
                "register the rule",
            )
        ]
    return install_violations(root, install_rule.exceptions)


def check() -> list[str]:
    """Adapter for scripts/run_quality_guards.py."""
    return [str(violation) for violation in run_check(REPO_ROOT)]
