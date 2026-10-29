"""Tests for .github/bump_version.py, which raises the version at each release.

The versioning job in .github/workflows/push.yml runs it after a merge to
master, before Towncrier builds CHANGELOG.md. It reads the pending fragments
through .github/changelog_fragments.py, the definition the PR check uses (rule
api.process.changelog-fragment), and stops at any file it can't read.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from tests.unit.changelog_fragment_support import (
    GITHUB_DIRECTORY,
    REPO,
    bump_version,
    changelog_fragments,
)

if TYPE_CHECKING:
    from pathlib import Path

bump_module = bump_version()

FRAGMENT_TEXT = "A change.\n"
UNREADABLE_SUMMARY = (
    "The release reads every file in changelog.d/, and 1 of them is not a "
    "fragment. Fix it in a pull request; the release stops until then.\n"
)


def _write(root: Path, relative_path: str, text: str = FRAGMENT_TEXT) -> None:
    file_path = root / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(text, encoding="utf-8")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Return a root holding the repository's pyproject.toml and changelog.d/."""
    (tmp_path / "pyproject.toml").write_text(
        (REPO / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _write(tmp_path, "changelog.d/.gitkeep", "")
    return tmp_path


@pytest.mark.parametrize(
    ("fragment_names", "expected_bump"),
    [
        (("1.fixed.md",), "patch"),
        (("1.changed.md",), "patch"),
        (("1.changed.md", "2.fixed.md"), "patch"),
        (("1.added.md",), "minor"),
        (("1.removed.md",), "minor"),
        (("1.removed.md", "2.fixed.md"), "minor"),
        (("1.breaking.md",), "major"),
        (("a.b.breaking.md", "1.added.md"), "major"),
        (("update-policyengine-bundle-6.11.1.changed.md",), "patch"),
    ],
)
def test_infer_bump_takes_the_largest_bump_a_pending_fragment_calls_for(
    repository: Path, fragment_names: tuple[str, ...], expected_bump: str
):
    for fragment_name in fragment_names:
        _write(repository, f"changelog.d/{fragment_name}")

    assert bump_module.infer_bump(repository) == expected_bump


def test_the_bump_table_has_a_bump_for_exactly_the_configured_types():
    definition = changelog_fragments().FragmentDefinition.load(REPO)

    assert bump_module.BUMP_BY_TYPE == {
        "breaking": "major",
        "added": "minor",
        "changed": "patch",
        "fixed": "patch",
        "removed": "minor",
    }
    assert set(bump_module.BUMP_BY_TYPE) == set(definition.types)


def test_infer_bump_refuses_types_the_bump_table_does_not_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    type_tables = "".join(
        f'\n[[tool.towncrier.type]]\ndirectory = "{fragment_type}"\n'
        for fragment_type in ("added", "fixed", "security")
    )
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.towncrier]\ndirectory = "changelog.d"\n{type_tables}',
        encoding="utf-8",
    )
    _write(tmp_path, "changelog.d/1.security.md")

    with pytest.raises(SystemExit) as exit_info:
        bump_module.infer_bump(tmp_path)

    assert exit_info.value.code == 1
    assert capsys.readouterr().err == (
        "The fragment types in [tool.towncrier] in pyproject.toml are added, "
        "fixed and security, but BUMP_BY_TYPE in .github/bump_version.py has a "
        "bump for breaking, added, changed, fixed and removed. Types with no "
        "bump: security. Bumps with no type: breaking, changed and removed. "
        "Change both together.\n"
    )


@pytest.mark.parametrize(
    ("relative_path", "text", "expected_problem"),
    [
        (
            "changelog.d/added/4083.md",
            FRAGMENT_TEXT,
            "changelog.d/added/4083.md is in a folder inside changelog.d/. The "
            "release reads only files directly in changelog.d/ and stops at "
            "anything else there. Move it to changelog.d/4083.added.md.",
        ),
        ("changelog.d/notes", FRAGMENT_TEXT, "is not named <name>.<type>.md"),
        ("changelog.d/1.added", FRAGMENT_TEXT, "is not named <name>.<type>.md"),
        ("changelog.d/.added.md", FRAGMENT_TEXT, "is not named <name>.<type>.md"),
        ("changelog.d/breaking.md", FRAGMENT_TEXT, "is not named <name>.<type>.md"),
        ("changelog.d/1.feature.md", FRAGMENT_TEXT, 'has the type "feature"'),
        ("changelog.d/1.added.md", "", "changelog.d/1.added.md is empty."),
        (
            "changelog.d/1.added.md",
            " \n",
            "changelog.d/1.added.md holds only whitespace.",
        ),
    ],
    ids=[
        "pull-request-4084",
        "no-extension",
        "no-md-extension",
        "no-name",
        "no-type",
        "unknown-type",
        "empty",
        "whitespace-only",
    ],
)
def test_infer_bump_stops_at_a_file_it_cannot_read(
    repository: Path,
    capsys: pytest.CaptureFixture[str],
    relative_path: str,
    text: str,
    expected_problem: str,
):
    _write(repository, "changelog.d/2.fixed.md")
    _write(repository, relative_path, text)

    with pytest.raises(SystemExit) as exit_info:
        bump_module.infer_bump(repository)

    assert exit_info.value.code == 1
    error_output = capsys.readouterr().err
    assert expected_problem in error_output
    assert error_output.endswith(UNREADABLE_SUMMARY)


def test_infer_bump_stops_at_an_empty_folder(
    repository: Path, capsys: pytest.CaptureFixture[str]
):
    _write(repository, "changelog.d/2.fixed.md")
    (repository / "changelog.d/vendored").mkdir()

    with pytest.raises(SystemExit) as exit_info:
        bump_module.infer_bump(repository)

    assert exit_info.value.code == 1
    assert capsys.readouterr().err == (
        "changelog.d/vendored is an empty folder or a submodule inside "
        "changelog.d/. The release reads only files directly in changelog.d/ "
        "and stops at anything else there. Delete it.\n" + UNREADABLE_SUMMARY
    )


def test_infer_bump_exits_when_only_gitkeep_is_present(
    repository: Path, capsys: pytest.CaptureFixture[str]
):
    with pytest.raises(SystemExit) as exit_info:
        bump_module.infer_bump(repository)

    assert exit_info.value.code == 1
    assert capsys.readouterr().err == (
        "No changelog fragments found in changelog.d/: there is nothing to release.\n"
    )


def _release_checkout(tmp_path: Path) -> Path:
    """Return a copy of the files the versioning job's bump step reads."""
    (tmp_path / ".github").mkdir()
    for script_name in ("bump_version.py", "changelog_fragments.py"):
        shutil.copy(GITHUB_DIRECTORY / script_name, tmp_path / ".github" / script_name)
    (tmp_path / "pyproject.toml").write_text(
        (REPO / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _write(tmp_path, "changelog.d/.gitkeep", "")
    return tmp_path


def _project_version(root: Path) -> tuple[int, int, int]:
    match = re.search(
        r'^version = "(\d+)\.(\d+)\.(\d+)"',
        (root / "pyproject.toml").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match is not None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def _run_bump(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the copied bump script as push.yml does: python .github/bump_version.py."""
    return subprocess.run(
        [sys.executable, ".github/bump_version.py"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


def test_the_script_raises_the_version_as_the_release_runs_it(tmp_path: Path):
    root = _release_checkout(tmp_path)
    _write(root, "changelog.d/4083.added.md")
    major, minor, _patch = _project_version(root)

    result = _run_bump(root)

    assert result.returncode == 0, result.stderr
    assert _project_version(root) == (major, minor + 1, 0)
    assert result.stdout.startswith("Version: ")
    assert result.stdout.splitlines()[0].endswith(f"-> {major}.{minor + 1}.0 (minor)")


def test_the_script_stops_at_pull_request_4084s_fragment(tmp_path: Path):
    root = _release_checkout(tmp_path)
    _write(root, "changelog.d/2.fixed.md")
    _write(root, "changelog.d/added/4083.md")
    version_before = _project_version(root)

    result = _run_bump(root)

    assert result.returncode == 1, result.stdout
    assert "Move it to changelog.d/4083.added.md." in result.stderr
    assert _project_version(root) == version_before
