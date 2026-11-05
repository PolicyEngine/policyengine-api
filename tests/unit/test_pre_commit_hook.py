"""A git pre-commit hook runs make quality (api.quality.pre-commit-hook).

make install turns on the hooks in .githooks with git config core.hooksPath
.githooks, a setting of the clone that every worktree shares and resolves
against its own checkout. pre-commit runs make quality from the root of the
working tree, and pre-merge-commit runs pre-commit for a merge that commits
without conflicts. make quality checks the working tree, so the hook first
requires it to hold exactly what is committed: no unstaged changes to tracked
files and no untracked files outside .gitignore. The commit stops, saying
why, when that isn't so, when a check fails, when ruff's fixes changed a
file, or when make, uv or the worktree's dev environment is missing.

These tests run the hooks in temporary repositories whose Makefile's quality
target stands in for the real checks, with a PATH of only the tools they
need, a stand-in uv, and no global or system git settings.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / ".githooks"
FIXTURES = REPO / "rules" / "fixtures" / "api.quality.pre-commit-hook"
# The tools the hooks, make install and these tests run, found through PATH.
TOOLS = ("git", "make", "sh", "find", "env")
# A stand-in for uv that records each call when UV_STUB_LOG is set.
STUB_UV = (
    '#!/bin/sh\nif [ -n "${UV_STUB_LOG:-}" ]; then\n'
    '  printf \'%s\\n\' "$*" >> "$UV_STUB_LOG"\nfi\nexit 0\n'
)
PASSING_QUALITY = 'quality:\n\t@echo checked >> "$$QUALITY_MARKER"\n'
FAILING_QUALITY = "quality:\n\t@echo 'mypy: 1 error'\n\t@exit 1\n"
FIXING_QUALITY = "quality:\n\t@printf 'VALUE = 1\\n' > module.py\n"
# The real Makefile's shape: quality runs quality-check through $(MAKE).
RECURSIVE_FAILING_QUALITY = (
    "quality:\n\t$(MAKE) quality-check\n\nquality-check:\n\t@exit 1\n"
)
# Fixes module.py, as ruff check --fix does, then fails, as mypy can after it.
FIXING_THEN_FAILING_QUALITY = (
    "quality:\n\t@printf 'VALUE = 1\\n' > module.py\n\t@echo 'mypy: 1 error'\n"
    "\t@exit 1\n"
)


def _environment(tmp_path: Path, *, missing: tuple[str, ...] = ()) -> dict[str, str]:
    """Return an environment whose PATH has only TOOLS and a stand-in uv.

    Tools named in ``missing`` are left out. No git or make settings from the
    run that started the test reach it.
    """
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    for tool in TOOLS:
        found = shutil.which(tool)
        if tool not in missing and found and not (tools / tool).exists():
            (tools / tool).symlink_to(found)
    if "uv" not in missing:
        (tools / "uv").write_text(STUB_UV)
        (tools / "uv").chmod(0o755)
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GIT_", "UV_"))
        and name not in {"MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "MAKEFILES"}
        and name != "MAKELEVEL"
    }
    environment.update(
        {
            "PATH": str(tools),
            "HOME": str(tmp_path),
            # git reads $XDG_CONFIG_HOME/git/ignore even without a global config.
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
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


def _make(
    cwd: Path, environment: dict[str, str], target: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", target],
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
    hook: Path | None = None,
    *,
    dev_environment: bool = True,
) -> Path:
    """Create a repository with one commit whose commits run the hooks.

    ``hook`` replaces .githooks/pre-commit with another file, such as a proof
    fixture.
    """
    repository = tmp_path / "repository"
    repository.mkdir(parents=True)
    shutil.copytree(HOOKS, repository / ".githooks")
    if hook is not None:
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


def _ran(tmp_path: Path) -> int:
    """Return how many times the stand-in quality target ran."""
    marker = tmp_path / "quality-ran"
    return len(marker.read_text().splitlines()) if marker.exists() else 0


def hook_problems(hook: Path, tmp_path: Path) -> list[str]:
    """Return how ``hook`` fails to stop a commit api.quality.pre-commit-hook stops."""
    problems = []
    for name, recipe, prepare, blocks in (
        ("a failing check", FAILING_QUALITY, None, True),
        ("ruff's fixes to a staged file", FIXING_QUALITY, None, True),
        (
            "an unstaged change make quality would check",
            PASSING_QUALITY,
            "unstaged",
            True,
        ),
        ("a missing uv", PASSING_QUALITY, "no uv", True),
        ("an untracked file", PASSING_QUALITY, "untracked", True),
        ("a missing dev environment", PASSING_QUALITY, "no venv", True),
        ("passing checks", PASSING_QUALITY, None, False),
    ):
        scenario = tmp_path / name.replace(" ", "-").replace("'", "")
        scenario.mkdir(parents=True)
        environment = _environment(
            scenario, missing=("uv",) if prepare == "no uv" else ()
        )
        repository = _repository(
            scenario, environment, recipe, hook, dev_environment=prepare != "no venv"
        )
        if prepare == "untracked":
            (repository / "scratch.py").write_text("SCRATCH = 0\n")
        if prepare == "unstaged":
            (repository / "other.py").write_text("OTHER = 1\n")
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
        "the hook lets a commit through after an unstaged change make quality "
        "would check",
        "the hook lets a commit through after a missing uv",
        "the hook lets a commit through after an untracked file",
        "the hook lets a commit through after a missing dev environment",
    ]
    assert accepted == []


def test_the_repository_s_hook_stops_what_it_should(tmp_path: Path):
    assert hook_problems(HOOKS / "pre-commit", tmp_path) == []


def test_a_commit_runs_make_quality(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)

    result = _commit_a_change(repository, environment)

    assert result.returncode == 0, result.stderr
    assert _ran(tmp_path) == 1
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


def test_fixes_from_an_earlier_failed_run_stop_the_next_commit(tmp_path: Path):
    # The first commit fails after ruff fixed module.py in the working tree;
    # the fix was never staged, so the next commit must not pass without it.
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, FIXING_THEN_FAILING_QUALITY)
    first = _commit_a_change(repository, environment)
    (repository / "Makefile").write_text(PASSING_QUALITY)
    _git(repository, environment, "add", "Makefile")

    second = _git(repository, environment, "commit", "-m", "change")

    assert first.returncode != 0
    assert second.returncode != 0
    assert "module.py" in second.stderr
    assert _commits(repository, environment) == 1


def test_unstaged_changes_stop_the_commit_and_are_named(tmp_path: Path):
    # make quality would check them, not what is committed. The name is shown
    # as it is, not quoted as git quotes names outside ASCII.
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / "données.py").write_text("DATA = 0\n")
    _git(repository, environment, "add", "données.py")
    (repository / "données.py").write_text("DATA = 1\n")

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "données.py" in result.stderr
    assert "git stash push --keep-index" in result.stderr
    assert _ran(tmp_path) == 0
    assert _commits(repository, environment) == 1


def test_untracked_files_stop_the_commit_and_are_named(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / "scratch_notes.py").write_text("import os\n")

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "scratch_notes.py" in result.stderr
    assert _ran(tmp_path) == 0
    assert _commits(repository, environment) == 1


def test_commit_all_runs_make_quality(tmp_path: Path):
    # git commit -a stages every tracked change, so nothing is left unstaged.
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / "module.py").write_text("VALUE = 2\n")
    (repository / "other.py").write_text("OTHER = 1\n")

    result = _git(repository, environment, "commit", "-a", "-m", "change")

    assert result.returncode == 0, result.stderr
    assert _ran(tmp_path) == 1


def test_a_merge_without_conflicts_runs_the_hook(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    _git(repository, environment, "checkout", "--quiet", "-b", "feature")
    (repository / "other.py").write_text("OTHER = 1\n")
    _git(repository, environment, "commit", "--quiet", "--no-verify", "-am", "feature")
    _git(repository, environment, "checkout", "--quiet", "master")
    (repository / "module.py").write_text("VALUE = 2\n")
    _git(repository, environment, "commit", "--quiet", "--no-verify", "-am", "master")
    (repository / "Makefile").write_text(FAILING_QUALITY)
    _git(repository, environment, "commit", "--quiet", "--no-verify", "-am", "fail")

    refused = _git(repository, environment, "merge", "--no-edit", "feature")
    _git(repository, environment, "merge", "--abort")
    (repository / "Makefile").write_text(PASSING_QUALITY)
    _git(repository, environment, "commit", "--quiet", "--no-verify", "-am", "pass")
    merged = _git(repository, environment, "merge", "--no-edit", "feature")

    assert refused.returncode != 0
    assert "make quality failed" in refused.stderr
    assert merged.returncode == 0, merged.stderr
    assert _ran(tmp_path) == 1


def test_make_flags_from_the_environment_cant_hide_a_failure(tmp_path: Path):
    environment = _environment(tmp_path)
    environment["MAKEFLAGS"] = "i"
    repository = _repository(tmp_path, environment, FAILING_QUALITY)

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert _commits(repository, environment) == 1


def test_a_missing_uv_stops_the_commit_with_a_message(tmp_path: Path):
    environment = _environment(tmp_path, missing=("uv",))
    repository = _repository(tmp_path, environment, PASSING_QUALITY)

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "uv isn't installed" in result.stderr
    assert "make install" in result.stderr
    assert _ran(tmp_path) == 0


def test_a_missing_make_stops_the_commit_with_a_message(tmp_path: Path):
    environment = _environment(tmp_path, missing=("make",))
    repository = _repository(tmp_path, environment, PASSING_QUALITY)

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "make isn't installed" in result.stderr


def test_a_missing_dev_environment_stops_the_commit_with_a_message(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(
        tmp_path, environment, PASSING_QUALITY, dev_environment=False
    )

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "no dev environment" in result.stderr
    assert "make install" in result.stderr
    assert _ran(tmp_path) == 0


def test_the_dev_environment_can_be_where_uv_project_environment_says(
    tmp_path: Path,
):
    environment = _environment(tmp_path)
    repository = _repository(
        tmp_path, environment, PASSING_QUALITY, dev_environment=False
    )
    (tmp_path / "environments" / "api").mkdir(parents=True)
    environment["UV_PROJECT_ENVIRONMENT"] = str(tmp_path / "environments" / "api")

    result = _commit_a_change(repository, environment)

    assert result.returncode == 0, result.stderr
    assert _ran(tmp_path) == 1


def test_each_worktree_runs_its_own_checkout_s_hook(tmp_path: Path):
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
    # The worktree's branch has a hook that stops every commit.
    (worktree / ".githooks" / "pre-commit").write_text(
        '#!/bin/sh\necho "the worktree\'s own hook ran" >&2\nexit 1\n'
    )
    _git(worktree, environment, "commit", "--quiet", "--no-verify", "-am", "hook")
    (worktree / "module.py").write_text("VALUE = 3\n")
    _git(worktree, environment, "add", "module.py")

    in_worktree = _git(worktree, environment, "commit", "-m", "in the worktree")
    in_clone = _commit_a_change(repository, environment)

    assert in_worktree.returncode != 0
    assert "the worktree's own hook ran" in in_worktree.stderr
    assert in_clone.returncode == 0, in_clone.stderr
    assert _ran(tmp_path) == 1


def _source_tree(directory: Path) -> Path:
    """Copy the files make install needs into ``directory``."""
    directory.mkdir(parents=True)
    shutil.copy(REPO / "Makefile", directory / "Makefile")
    shutil.copytree(HOOKS, directory / ".githooks")
    return directory


def test_make_install_turns_the_hook_on(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _source_tree(tmp_path / "repository")
    _git(repository, environment, "init", "--quiet")

    installed = _make(repository, environment, "install")

    assert installed.returncode == 0, installed.stderr
    hooks_path = _git(repository, environment, "config", "core.hooksPath")
    assert hooks_path.stdout.strip() == ".githooks"


def test_make_install_in_a_linked_worktree_turns_the_hook_on(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _source_tree(tmp_path / "repository")
    _git(repository, environment, "init", "--quiet", "--initial-branch=master")
    _git(repository, environment, "add", ".")
    _git(repository, environment, "commit", "--quiet", "--no-verify", "-m", "start")
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

    installed = _make(worktree, environment, "install")

    assert installed.returncode == 0, installed.stderr
    hooks_path = _git(repository, environment, "config", "core.hooksPath")
    assert hooks_path.stdout.strip() == ".githooks"


def test_make_install_outside_a_git_repository_still_installs(tmp_path: Path):
    # A Docker build or a source archive has no repository to configure.
    environment = _environment(tmp_path)
    environment["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    environment["UV_STUB_LOG"] = str(tmp_path / "uv-calls")
    directory = _source_tree(tmp_path / "source")

    installed = _make(directory, environment, "install")

    assert installed.returncode == 0, installed.stderr
    assert (tmp_path / "uv-calls").read_text() == "sync --frozen --extra dev\n"


def test_make_install_leaves_an_enclosing_repository_alone(tmp_path: Path):
    # A source archive unpacked inside another repository: that repository's
    # settings and hooks aren't make install's to change.
    environment = _environment(tmp_path)
    environment["UV_STUB_LOG"] = str(tmp_path / "uv-calls")
    enclosing = tmp_path / "enclosing"
    enclosing.mkdir()
    _git(enclosing, environment, "init", "--quiet")
    directory = _source_tree(enclosing / "vendor" / "policyengine-api")

    installed = _make(directory, environment, "install")

    assert installed.returncode == 0, installed.stderr
    assert "isn't the root of a git working tree" in installed.stderr
    hooks_path = _git(enclosing, environment, "config", "core.hooksPath")
    assert hooks_path.stdout == ""
    assert (tmp_path / "uv-calls").read_text() == "sync --frozen --extra dev\n"


def test_make_install_keeps_another_hooks_path(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _source_tree(tmp_path / "repository")
    _git(repository, environment, "init", "--quiet")
    _git(repository, environment, "config", "core.hooksPath", "/team/hooks")

    installed = _make(repository, environment, "install")

    assert installed.returncode == 0, installed.stderr
    assert "core.hooksPath is already /team/hooks" in installed.stderr
    hooks_path = _git(repository, environment, "config", "core.hooksPath")
    assert hooks_path.stdout.strip() == "/team/hooks"


def test_make_install_keeps_the_clone_s_own_hooks_running(tmp_path: Path):
    # core.hooksPath would stop git running the hooks in .git/hooks.
    environment = _environment(tmp_path)
    repository = _source_tree(tmp_path / "repository")
    _git(repository, environment, "init", "--quiet")
    own_hook = repository / ".git" / "hooks" / "pre-push"
    own_hook.write_text("#!/bin/sh\nexit 0\n")
    own_hook.chmod(0o755)

    installed = _make(repository, environment, "install")

    assert installed.returncode == 0, installed.stderr
    assert "pre-push" in installed.stderr
    hooks_path = _git(repository, environment, "config", "core.hooksPath")
    assert hooks_path.stdout == ""


def test_python_files_hidden_by_local_excludes_stop_the_commit(tmp_path: Path):
    # mypy and Import Linter read every Python file on disk, whatever git
    # ignores outside the repository's .gitignore files.
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / "helper.py").write_text("HELPER = 0\n")
    (repository / ".git" / "info" / "exclude").write_text("helper.py\n")

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "helper.py" in result.stderr
    assert _ran(tmp_path) == 0


def test_other_files_hidden_by_local_excludes_dont_stop_the_commit(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / "notes.txt").write_text("notes\n")
    (repository / ".git" / "info" / "exclude").write_text("notes.txt\n")

    result = _commit_a_change(repository, environment)

    assert result.returncode == 0, result.stderr
    assert _ran(tmp_path) == 1


@pytest.mark.parametrize("variable", ["MAKE", "MAKE_COMMAND"])
def test_make_from_the_environment_cant_skip_the_checks(variable, tmp_path: Path):
    # make takes $(MAKE) from the environment, so `true` would skip
    # quality-check.
    environment = _environment(tmp_path)
    # An absolute path: the test's PATH has no true.
    environment[variable] = shutil.which("true") or "/usr/bin/true"
    repository = _repository(tmp_path, environment, RECURSIVE_FAILING_QUALITY)

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert _commits(repository, environment) == 1


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_files_git_doesnt_compare_stop_the_commit(flag, tmp_path: Path):
    # git diff doesn't compare them with the commit, so make quality could
    # check a copy the commit doesn't hold.
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    _git(repository, environment, "update-index", flag, "other.py")
    (repository / "other.py").write_text("OTHER = 1\n")

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "other.py" in result.stderr
    assert _ran(tmp_path) == 0


def test_make_install_keeps_a_symlinked_hook_running(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _source_tree(tmp_path / "repository")
    _git(repository, environment, "init", "--quiet")
    script = tmp_path / "team-pre-push"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    (repository / ".git" / "hooks" / "pre-push").symlink_to(script)

    installed = _make(repository, environment, "install")

    assert installed.returncode == 0, installed.stderr
    assert "pre-push" in installed.stderr
    hooks_path = _git(repository, environment, "config", "core.hooksPath")
    assert hooks_path.stdout == ""


def test_make_install_keeps_a_symlinked_hooks_directory_running(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _source_tree(tmp_path / "repository")
    _git(repository, environment, "init", "--quiet")
    team_hooks = tmp_path / "team-hooks"
    team_hooks.mkdir()
    (team_hooks / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    (team_hooks / "pre-push").chmod(0o755)
    shutil.rmtree(repository / ".git" / "hooks")
    (repository / ".git" / "hooks").symlink_to(team_hooks)

    installed = _make(repository, environment, "install")

    assert installed.returncode == 0, installed.stderr
    assert "pre-push" in installed.stderr
    hooks_path = _git(repository, environment, "config", "core.hooksPath")
    assert hooks_path.stdout == ""


def test_make_install_still_installs_when_git_config_is_locked(tmp_path: Path):
    # Another git command, or make install in another worktree of the clone,
    # can hold .git/config's lock.
    environment = _environment(tmp_path)
    environment["UV_STUB_LOG"] = str(tmp_path / "uv-calls")
    repository = _source_tree(tmp_path / "repository")
    _git(repository, environment, "init", "--quiet")
    (repository / ".git" / "config.lock").write_text("")

    installed = _make(repository, environment, "install")

    assert installed.returncode == 0, installed.stderr
    assert "core.hooksPath" in installed.stderr
    assert (tmp_path / "uv-calls").read_text() == "sync --frozen --extra dev\n"


def test_a_commit_passes_in_a_utf8_locale(tmp_path: Path):
    # bash 3.2, macOS's /bin/sh, matches uppercase letters with [a-z] in
    # UTF-8 locales, and git ls-files -v marks every ordinary file H.
    environment = _environment(tmp_path)
    environment["LANG"] = environment["LC_ALL"] = "en_US.UTF-8"
    repository = _repository(tmp_path, environment, PASSING_QUALITY)

    result = _commit_a_change(repository, environment)

    assert result.returncode == 0, result.stderr
    assert _ran(tmp_path) == 1


@pytest.mark.parametrize("name", ["ruff.toml", "mypy.ini", "lib/pyproject.toml"])
def test_tool_settings_hidden_by_local_excludes_stop_the_commit(name, tmp_path: Path):
    # ruff and mypy read their settings from these files before
    # pyproject.toml, whatever git ignores.
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    settings = repository / name
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("")
    (repository / ".git" / "info" / "exclude").write_text(f"{name}\n")

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert name.split("/")[0] in result.stderr
    assert _ran(tmp_path) == 0


def test_a_hidden_directory_of_python_files_stops_the_commit(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / "lib").mkdir()
    (repository / "lib" / "helper.py").write_text("HELPER = 0\n")
    (repository / ".git" / "info" / "exclude").write_text("lib/\n")

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "lib/" in result.stderr


def test_a_hidden_virtual_environment_doesnt_stop_the_commit(tmp_path: Path):
    # No check reads a virtual environment's files.
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / "venv" / "lib").mkdir(parents=True)
    (repository / "venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (repository / "venv" / "lib" / "site.py").write_text("SITE = 0\n")
    (repository / ".git" / "info" / "exclude").write_text("venv/\n")

    result = _commit_a_change(repository, environment)

    assert result.returncode == 0, result.stderr
    assert _ran(tmp_path) == 1


def test_tracked_python_files_local_excludes_match_stop_the_commit(tmp_path: Path):
    # ruff skips files .git/info/exclude matches, even tracked ones, which
    # CI checks.
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / ".git" / "info" / "exclude").write_text("other.py\n")

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "other.py" in result.stderr
    assert "ruff" in result.stderr
    assert _ran(tmp_path) == 0


def test_a_case_only_rename_stops_the_commit(tmp_path: Path):
    # On a file system that ignores case, git status shows nothing, but the
    # checks would read Module.py while the commit holds module.py.
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / "other.py").rename(repository / "Other.py")

    result = _commit_a_change(repository, environment)

    assert result.returncode != 0
    assert "Other.py" in result.stderr or "other.py" in result.stderr
    assert _ran(tmp_path) == 0


def test_a_commit_of_some_paths_says_how_to_commit_the_rest(tmp_path: Path):
    environment = _environment(tmp_path)
    repository = _repository(tmp_path, environment, PASSING_QUALITY)
    (repository / "other.py").write_text("OTHER = 1\n")
    _git(repository, environment, "add", "other.py")
    (repository / "module.py").write_text("VALUE = 2\n")

    result = _git(repository, environment, "commit", "-m", "module", "module.py")

    assert result.returncode != 0
    assert "without paths" in result.stderr


def test_the_hooks_are_executable_in_git(tmp_path: Path):
    environment = _environment(tmp_path)
    listed = _git(
        REPO, environment, "ls-files", "--stage", "--", ".githooks/"
    ).stdout.splitlines()
    modes = {entry.split("\t")[1]: entry.split()[0] for entry in listed}

    assert modes[".githooks/pre-commit"] == "100755"
    assert modes[".githooks/pre-merge-commit"] == "100755"
