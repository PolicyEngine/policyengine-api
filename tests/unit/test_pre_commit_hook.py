"""A git pre-commit hook runs make quality (api.quality.pre-commit-hook).

make install turns on .githooks/pre-commit with git config core.hooksPath
.githooks, which every worktree of the clone shares. The hook runs make
quality from the root of the working tree. It fails the commit when a check
fails, when ruff's fixes changed files that still need staging, or when make,
uv or the worktree's dev environment (.venv) is missing. These tests run it
in temporary repositories whose Makefile's quality target stands in for the
real checks.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".githooks" / "pre-commit"
FIXTURES = REPO / "rules" / "fixtures" / "api.quality.pre-commit-hook"
# Variables of make's own, and git settings outside the test repository, that
# the test's git and make mustn't inherit.
LEAKING_VARIABLES = frozenset(
    {"MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEFILES", "MAKELEVEL", "GIT_DIR"}
)
STUB_UV = "#!/bin/sh\nexit 0\n"
PASSING_QUALITY = 'quality:\n\t@echo checked >> "$$QUALITY_MARKER"\n'
FAILING_QUALITY = "quality:\n\t@echo 'mypy: 1 error'\n\t@exit 1\n"
FIXING_QUALITY = "quality:\n\t@printf 'VALUE = 1\\n' > module.py\n"


def _environment(tmp_path: Path, *, with_uv: bool = True) -> dict[str, str]:
    """Return an environment with a stand-in uv and no global git settings."""
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    if with_uv:
        (stubs / "uv").write_text(STUB_UV)
        (stubs / "uv").chmod(0o755)
    search_path = [str(stubs)]
    for tool in ("git", "make", "sh"):
        directory = str(Path(shutil.which(tool) or "/usr/bin").parent)
        if directory not in search_path:
            search_path.append(directory)
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in LEAKING_VARIABLES and not name.startswith("GIT_")
    }
    environment.update(
        {
            "PATH": os.pathsep.join([*search_path, "/usr/bin", "/bin"]),
            "HOME": str(tmp_path),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "QUALITY_MARKER": str(tmp_path / "quality-ran"),
        }
    )
    return environment


def _git(
    cwd: Path, environment: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _repository(
    tmp_path: Path,
    environment: dict[str, str],
    quality_recipe: str,
    hook: Path = HOOK,
    *,
    dev_environment: bool = True,
) -> Path:
    """Create a repository whose commits run ``hook``, with one commit made."""
    repository = tmp_path / "repository"
    (repository / ".githooks").mkdir(parents=True)
    shutil.copy(hook, repository / ".githooks" / "pre-commit")
    (repository / ".githooks" / "pre-commit").chmod(0o755)
    (repository / "Makefile").write_text(quality_recipe)
    (repository / "module.py").write_text("VALUE = 0\n")
    (repository / "other.py").write_text("OTHER = 0\n")
    (repository / ".gitignore").write_text(".venv/\n")
    if dev_environment:
        (repository / ".venv").mkdir()
    _git(repository, environment, "init", "--quiet", "--initial-branch=master")
    _git(repository, environment, "add", ".")
    _git(repository, environment, "commit", "--quiet", "-m", "start")
    _git(repository, environment, "config", "core.hooksPath", ".githooks")
    return repository


def _commit_a_change(
    repository: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    (repository / "module.py").write_text("VALUE = 2\n")
    _git(repository, environment, "add", "module.py")
    return _git(repository, environment, "commit", "-m", "change")


def _commits(repository: Path, environment: dict[str, str]) -> int:
    counted = _git(repository, environment, "rev-list", "--count", "HEAD")
    return int(counted.stdout)


def hook_problems(hook: Path, tmp_path: Path) -> list[str]:
    """Return how ``hook`` fails to stop a commit api.quality.pre-commit-hook stops."""
    problems = []
    for name, recipe, blocks in (
        ("a failing check", FAILING_QUALITY, True),
        ("ruff's fixes to a staged file", FIXING_QUALITY, True),
        ("passing checks", PASSING_QUALITY, False),
    ):
        scenario = tmp_path / name.replace(" ", "-").replace("'", "")
        scenario.mkdir(parents=True)
        environment = _environment(scenario)
        repository = _repository(scenario, environment, recipe, hook)
        result = _commit_a_change(repository, environment)
        if blocks and result.returncode == 0:
            problems.append(f"the hook lets a commit through after {name}")
        if not blocks and result.returncode != 0:
            problems.append(f"the hook stops a commit after {name}")
    return problems


def test_rule_proof_pre_commit_hook(tmp_path: Path):
    rejected = hook_problems(FIXTURES / "rejected" / "pre-commit", tmp_path / "bad")
    accepted = hook_problems(FIXTURES / "accepted" / "pre-commit", tmp_path / "good")

    assert rejected == [
        "the hook lets a commit through after a failing check",
        "the hook lets a commit through after ruff's fixes to a staged file",
    ]
    assert accepted == []


def test_the_repository_s_hook_stops_what_it_should(tmp_path: Path):
    assert hook_problems(HOOK, tmp_path) == []


def test_a_commit_runs_make_quality(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)

    result = _commit_a_change(repository, environment)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "quality-ran").read_text() == "checked\n"
    assert _commits(repository, environment) == 2


def test_a_failing_check_stops_the_commit(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, FAILING_QUALITY)

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "make quality failed" in result.stderr
    assert _commits(repository, environment) == 1


def test_fixes_that_need_staging_stop_the_commit_and_are_named(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, FIXING_QUALITY)

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "module.py" in result.stderr
    assert "stage" in result.stderr
    assert _commits(repository, environment) == 1


def test_unstaged_changes_make_quality_leaves_alone_dont_stop_the_commit(
    tmp_path: Path,
):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / "other.py").write_text("OTHER = 1\n")

    result = _commit_a_change(repository, environment)

    assert result.returncode == 0, result.stderr
    assert _commits(repository, environment) == 2


def test_a_missing_uv_stops_the_commit_with_a_message(tmp_path: Path):
    environment = _environment(tmp_path, with_uv=False)
    if shutil.which("uv", path=environment["PATH"]):
        pytest.skip("uv is installed in a system directory")
    repository = _repository(tmp_path, environment, PASSING_QUALITY)

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "uv isn't installed" in result.stderr
    assert "make install" in result.stderr
    assert not (tmp_path / "quality-ran").exists()


def test_a_missing_dev_environment_stops_the_commit_with_a_message(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(
        tmp_path, environment, PASSING_QUALITY, dev_environment=False
    )

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "no dev environment" in result.stderr
    assert "make install" in result.stderr
    assert not (tmp_path / "quality-ran").exists()


def test_every_worktree_of_the_clone_runs_the_hook(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    worktree = tmp_path / "worktree"
    _git(
        repository,
        environment,
        "worktree",
        "add",
        "--quiet",
        "-b",
        "other",
        str(worktree),
    )
    (worktree / ".venv").mkdir()
    (worktree / "module.py").write_text("VALUE = 3\n")
    _git(worktree, environment, "add", "module.py")

    result = _git(worktree, environment, "commit", "-m", "change in a worktree")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "quality-ran").read_text() == "checked\n"


def test_make_install_turns_the_hook_on(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = tmp_path / "repository"
    repository.mkdir()
    shutil.copy(REPO / "Makefile", repository / "Makefile")
    _git(repository, environment, "init", "--quiet")

    installed = subprocess.run(
        ["make", "install"],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr
    hooks_path = _git(repository, environment, "config", "core.hooksPath")
    assert hooks_path.stdout.strip() == ".githooks"


def test_make_install_outside_a_git_repository_still_installs(tmp_path: Path):
    # A Docker build or a source archive has no repository to configure.
    environment = _environment(tmp_path)
    directory = tmp_path / "source"
    directory.mkdir()
    shutil.copy(REPO / "Makefile", directory / "Makefile")
    environment["GIT_CEILING_DIRECTORIES"] = str(tmp_path)

    installed = subprocess.run(
        ["make", "install"],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr


def test_the_hook_is_executable_in_git():
    listed = subprocess.run(
        ["git", "ls-files", "--stage", "--", ".githooks/pre-commit"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert listed.startswith("100755 ")
