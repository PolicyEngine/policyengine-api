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
    from collections.abc import Callable, Iterable, Iterator

    Classifier = Callable[[str], "tuple[bool, bool] | None"]

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_RULE = "api.dependencies.install-from-lock"
TEST_RULE = "api.dependencies.test-from-lock"
LOCK_RULE = "api.dependencies.lock-committed"
RELOCK_RULE = "api.dependencies.scheduled-relock"
PINNED_TOOL = "pinned-tool"
# Proof fixtures hold deliberate violations; they are scanned by their tests.
EXCLUDED_PREFIXES = ("scripts/rules/tests/fixtures/", "rules/fixtures/")
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
_TEST_COMMAND = re.compile(
    r"\bpytest\b|\bcoverage\s+run\b|-m\s+unittest\b|\bunittest\s+discover\b"
    r"|(?:^|\s)(?:tox|nox)(?:\s|$)"
)
_SCRIPT_REFERENCE = re.compile(r"\.github/[\w./-]+\.sh")
_MAKE_TARGET_REFERENCE = re.compile(r"\bmake ([\w-]+)")
_MAKE_TARGET_HEADER = re.compile(r"^([\w-]+)\s*:(?!=)")
_RUN_KEY = re.compile(r"^(?P<indent>\s*)(?:-\s+)?run:(?P<value>.*)$")
_PULL_REQUEST_TRIGGERS = {"pull_request", "pull_request_target"}
_ON_KEY = re.compile(r"""^["']?on["']?:\s*(?P<inline>.*)$""")
_TRIGGER_KEY = re.compile(r"^(?P<indent>\s+)(?P<name>[\w-]+):")
_LOCK_CHECK = re.compile(r"\buv\s+lock\b.*--(?:check|locked)\b")
_RELOCK = re.compile(r"\buv\s+lock\b")
_UPGRADE_FLAG = re.compile(
    r"(?:^|[\s(])(?:--upgrade|--upgrade-package|-U|-P)(?=[\s=)]|$)", re.MULTILINE
)
_ARRAY_EXPANSION = re.compile(r"\$\{(\w+)\[@\]\}")
_OPENS_PULL_REQUEST = re.compile(r"\bgh\s+pr\s+(?:create|edit)\b")
_PROJECT_OPTION = re.compile(r"--(?:project|directory)[=\s]+(?P<directory>\S+)")
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
    """One command or call in a scanned file that installs packages or runs tests."""

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
        return "action"
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
                yield from _sites(path, _commands(literal), classify_command)
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
            yield from _sites(path, [command], classify_command)


def classify_test_command(command: str) -> tuple[bool, bool] | None:
    """Return ``(locked, False)`` for a command that runs tests, else None."""
    if not _TEST_COMMAND.search(command):
        return None
    installs = classify_command(command)
    if installs is not None and _UV_RUN.search(command) is None:
        return None
    return installs == (True, False), False


def _sites(path: str, commands: Iterable[str], classify: Classifier) -> Iterator[Site]:
    for command in commands:
        classified = classify(command)
        if classified is not None:
            yield Site(path, command, *classified)


def _workflow_commands(text: str) -> Iterator[str]:
    jobs, _ = parse_jobs(text)
    for job in jobs.values():
        for run_block in job.run_blocks:
            yield from _commands(run_block.text)


def _action_commands(text: str) -> Iterator[str]:
    """Yield the commands of a composite action's ``run:`` steps."""
    action_lines = text.splitlines()
    for position, action_line in enumerate(action_lines):
        run_key = _RUN_KEY.match(action_line)
        if run_key is None:
            continue
        value = run_key.group("value").strip()
        if value and value[0] not in "|>":
            yield from _commands(value)
            continue
        key_indent = len(run_key.group("indent"))
        block = []
        for block_line in action_lines[position + 1 :]:
            if (
                block_line.strip()
                and len(block_line) - len(block_line.lstrip()) <= key_indent
            ):
                break
            block.append(block_line)
        yield from _commands("\n".join(block))


def _makefile_commands(text: str) -> Iterator[str]:
    recipe_text = "\n".join(
        makefile_line
        for makefile_line in _CONTINUATION.sub(" ", text).splitlines()
        if makefile_line.startswith("\t")
    )
    yield from _commands(recipe_text)


_COMMAND_FINDERS: dict[str, Callable[[str], Iterator[str]]] = {
    "workflow": _workflow_commands,
    "action": _action_commands,
    "shell": _commands,
    "makefile": _makefile_commands,
    "dockerfile": _commands,
}


def _scanned_texts(root: Path) -> Iterator[tuple[str, str, str]]:
    for path, kind in sorted(scanned_files(root).items()):
        yield path, kind, (root / path).read_text(encoding="utf-8", errors="replace")


def install_sites(root: Path = REPO_ROOT) -> list[Site]:
    """Return every install site in the scanned files."""
    sites: list[Site] = []
    for path, kind, text in _scanned_texts(root):
        if kind == "python":
            sites += _python_sites(path, text)
        else:
            sites += _sites(path, _COMMAND_FINDERS[kind](text), classify_command)
    return sites


def unlocked_install_sites(root: Path = REPO_ROOT) -> list[Site]:
    """Return every install site that does not install exactly what uv.lock pins."""
    return [site for site in install_sites(root) if not site.locked]


def unlocked_test_commands(root: Path = REPO_ROOT) -> list[Site]:
    """Return every test command that does not run through uv run --frozen."""
    sites: list[Site] = []
    for path, kind, text in _scanned_texts(root):
        if kind in _COMMAND_FINDERS:
            commands = _COMMAND_FINDERS[kind](text)
            sites += _sites(path, commands, classify_test_command)
    return [site for site in sites if not site.locked]


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


_SITE_PROBLEMS = {
    INSTALL_RULE: (
        "installs packages outside uv.lock",
        "install with uv sync --frozen or run with uv run --frozen",
    ),
    TEST_RULE: (
        "runs tests outside the uv.lock environment",
        "run the tests with uv run --frozen",
    ),
}


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
    problem, fix = _SITE_PROBLEMS[rule_id]
    for site in sites:
        if not any(_matches(exception, site) for exception in exceptions):
            violations.append(
                Violation(
                    rule_id,
                    "locked-installs",
                    f"{site.path}: '{site.command}' {problem}",
                    f"{fix}; if locking is not possible, register a "
                    "[[rule.exception]] "
                    "(docs/engineering/skills/dependencies.md#exceptions)",
                )
            )
    return violations


def install_violations(
    root: Path, exceptions: Iterable[RuleException]
) -> list[Violation]:
    """Report unlocked installs under ``root`` that ``exceptions`` do not cover."""
    return exception_violations(INSTALL_RULE, unlocked_install_sites(root), exceptions)


def makefile_recipes(root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """Return each root Makefile target's recipe lines."""
    makefile = root / "Makefile"
    if not makefile.is_file():
        return {}
    recipes: dict[str, list[str]] = {}
    current_target = None
    for makefile_line in makefile.read_text(encoding="utf-8").splitlines():
        header = _MAKE_TARGET_HEADER.match(makefile_line)
        if header is not None and header.group(1) != ".PHONY":
            current_target = header.group(1)
            recipes[current_target] = []
        elif makefile_line.startswith("\t") and current_target is not None:
            recipes[current_target].append(makefile_line.strip())
        elif makefile_line.strip():
            current_target = None
    return recipes


def executed_lines(
    root: Path, command_text: str, visited: set[str] | None = None
) -> list[str]:
    """Return the command's lines plus those of the scripts and Make targets it runs."""
    visited = set() if visited is None else visited
    recipes = makefile_recipes(root)
    executed = []
    for command_line in command_text.splitlines():
        if command_line.lstrip().startswith("#"):
            continue
        executed.append(command_line)
        for script_path in _SCRIPT_REFERENCE.findall(command_line):
            if script_path in visited or not (root / script_path).is_file():
                continue
            visited.add(script_path)
            script_text = (root / script_path).read_text(encoding="utf-8")
            executed += executed_lines(root, script_text, visited)
        for target in _MAKE_TARGET_REFERENCE.findall(command_line):
            if f"make {target}" in visited or target not in recipes:
                continue
            visited.add(f"make {target}")
            executed += executed_lines(root, "\n".join(recipes[target]), visited)
    return executed


def _workflow_job_commands(root: Path, path: str) -> dict[str, list[str]]:
    """Return each job's commands, including the scripts and Make targets it runs."""
    jobs, _ = parse_jobs((root / path).read_text(encoding="utf-8"))
    return {
        job_id: list(
            _commands(
                "\n".join(
                    executed_line
                    for run_block in job.run_blocks
                    for executed_line in executed_lines(root, run_block.text)
                )
            )
        )
        for job_id, job in jobs.items()
    }


def workflow_triggers(text: str) -> set[str]:
    """Return the event names in a workflow's top-level ``on:``."""
    lines = [raw_line.split(" #")[0].rstrip() for raw_line in text.splitlines()]
    for position, workflow_line in enumerate(lines):
        on_key = _ON_KEY.match(workflow_line)
        if on_key is None:
            continue
        inline = on_key.group("inline").strip()
        if inline:
            return {name.strip() for name in inline.strip("[]").split(",")}
        triggers: set[str] = set()
        trigger_indent = None
        for trigger_line in lines[position + 1 :]:
            if trigger_line and not trigger_line[0].isspace():
                break
            key = _TRIGGER_KEY.match(trigger_line)
            if key is None or trigger_line.lstrip().startswith("#"):
                continue
            trigger_indent = trigger_indent or key.group("indent")
            if key.group("indent") == trigger_indent:
                triggers.add(key.group("name"))
        return triggers
    return set()


def _project_directory(command: str) -> str:
    option = _PROJECT_OPTION.search(command)
    return "." if option is None else option.group("directory").rstrip("/")


def _locked_directories(root: Path, name: str) -> list[str]:
    return sorted(
        Path(path).parent.as_posix()
        for path in _tracked_files(root)
        if Path(path).name == name and not path.startswith(EXCLUDED_PREFIXES)
    )


def _workflows(root: Path) -> list[str]:
    return sorted(
        path for path, kind in scanned_files(root).items() if kind == "workflow"
    )


def lock_violations(root: Path = REPO_ROOT) -> list[Violation]:
    """Report projects without a committed uv.lock, or whose lock PR CI never checks."""
    locks = set(_locked_directories(root, "uv.lock"))
    projects = _locked_directories(root, "pyproject.toml")
    violations = [
        Violation(
            LOCK_RULE,
            "locked-installs",
            f"{project} has a pyproject.toml but no committed uv.lock",
            f"run uv lock in {project} and commit uv.lock",
        )
        for project in projects
        if project not in locks
    ]
    checked = {
        _project_directory(command)
        for path in _workflows(root)
        if workflow_triggers((root / path).read_text(encoding="utf-8"))
        & _PULL_REQUEST_TRIGGERS
        for commands in _workflow_job_commands(root, path).values()
        for command in commands
        if _LOCK_CHECK.search(command)
    }
    violations += [
        Violation(
            LOCK_RULE,
            "locked-installs",
            f"no pull request job runs uv lock --check for {project}",
            "add a pull request CI step that runs uv lock --check for it",
        )
        for project in projects
        if project not in checked
    ]
    return violations


def _upgrades(relock: str, job_text: str) -> bool:
    """Whether a ``uv lock`` command upgrades, directly or through an array it expands.

    The array form is ``arguments+=(--upgrade-package name)`` followed by
    ``uv lock "${arguments[@]}"``.
    """
    if _UPGRADE_FLAG.search(relock):
        return True
    for array_name in _ARRAY_EXPANSION.findall(relock):
        for assignment in re.finditer(
            rf"\b{re.escape(array_name)}\+?=\((?P<items>[^)]*)\)", job_text
        ):
            if _UPGRADE_FLAG.search(assignment.group("items")):
                return True
    return False


def _relocked_directories(root: Path, path: str) -> set[str] | None:
    """Return what a scheduled workflow's relock jobs relock, or None if none do."""
    jobs, _ = parse_jobs((root / path).read_text(encoding="utf-8"))
    relocked = None
    for job_id, commands in _workflow_job_commands(root, path).items():
        job_text = "\n".join(commands)
        relocks = [
            command
            for command in commands
            if _RELOCK.search(command)
            and not _LOCK_CHECK.search(command)
            and _upgrades(command, job_text)
        ]
        opens_pull_request = _OPENS_PULL_REQUEST.search(job_text) is not None or any(
            "create-pull-request" in action for action in jobs[job_id].step_uses
        )
        if relocks and opens_pull_request:
            relocked = (relocked or set()) | {
                _project_directory(command) for command in relocks
            }
    return relocked


def relock_violations(root: Path = REPO_ROOT) -> list[Violation]:
    """Report when no scheduled job relocks every uv.lock and proposes it as a PR."""
    relocked: set[str] | None = None
    for path in _workflows(root):
        if "schedule" not in workflow_triggers(
            (root / path).read_text(encoding="utf-8")
        ):
            continue
        workflow_relocks = _relocked_directories(root, path)
        if workflow_relocks is not None:
            relocked = (relocked or set()) | workflow_relocks
    if relocked is None:
        return [
            Violation(
                RELOCK_RULE,
                "locked-installs",
                "no scheduled workflow job relocks uv.lock with upgrades "
                "and opens or updates a pull request",
                "add a workflow on a schedule that runs uv lock --upgrade (or "
                "--upgrade-package) and gh pr create",
            )
        ]
    return [
        Violation(
            RELOCK_RULE,
            "locked-installs",
            f"the scheduled relock does not relock {directory}/uv.lock".replace(
                "./", ""
            ),
            "relock that project in the scheduled relock job",
        )
        for directory in _locked_directories(root, "uv.lock")
        if directory not in relocked
    ]


def test_command_violations(
    root: Path, exceptions: Iterable[RuleException]
) -> list[Violation]:
    """Report test commands under ``root`` that run outside the locked environment."""
    return exception_violations(TEST_RULE, unlocked_test_commands(root), exceptions)


def run_check(root: Path = REPO_ROOT) -> list[Violation]:
    """Load the registry and return every violation of the four uv.lock rules."""
    registry, violations = load_registry(root)
    if registry is None:
        return violations
    exceptions = {
        rule.id: rule.exceptions
        for rule in registry.rules
        if rule.id in {LOCK_RULE, INSTALL_RULE, TEST_RULE, RELOCK_RULE}
    }
    missing = [
        rule_id
        for rule_id in (LOCK_RULE, INSTALL_RULE, TEST_RULE, RELOCK_RULE)
        if rule_id not in exceptions
    ]
    if missing:
        return [
            Violation(
                None,
                "locked-installs",
                f"rules/registry.toml has no rule {rule_id}",
                "register the rule",
            )
            for rule_id in missing
        ]
    return (
        lock_violations(root)
        + install_violations(root, exceptions[INSTALL_RULE])
        + test_command_violations(root, exceptions[TEST_RULE])
        + relock_violations(root)
    )


def check() -> list[str]:
    """Adapter for scripts/run_quality_guards.py."""
    return [str(violation) for violation in run_check(REPO_ROOT)]
