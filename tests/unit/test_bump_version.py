"""Characterization tests for the changelog-driven version bump inference."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

BUMP_VERSION_PATH = Path(__file__).parents[2] / ".github" / "bump_version.py"


def _load_bump_version() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bump_version", BUMP_VERSION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _changelog_dir(tmp_path: Path, *fragment_names: str) -> Path:
    changelog_dir = tmp_path / "changelog.d"
    changelog_dir.mkdir()
    for name in fragment_names:
        (changelog_dir / name).write_text("A change.\n")
    return changelog_dir


@pytest.mark.parametrize(
    ("fragment_names", "expected_bump"),
    [
        (("1.fixed.md",), "patch"),
        (("1.fixed",), "patch"),
        (("notes",), "patch"),
        (("1.added.md",), "minor"),
        (("1.added",), "minor"),
        (("1.removed.md", "2.fixed.md"), "minor"),
        (("a.b.breaking.md", "1.added.md"), "major"),
        (("1.breaking",), "major"),
        (("breaking.md",), "patch"),
        ((".added.md",), "minor"),
        (("1.changed.md", ".gitkeep"), "patch"),
    ],
)
def test_infer_bump_reads_the_category_from_the_suffix_or_the_stem(
    tmp_path: Path, fragment_names: tuple[str, ...], expected_bump: str
) -> None:
    bump_version = _load_bump_version()

    assert (
        bump_version.infer_bump(_changelog_dir(tmp_path, *fragment_names))
        == expected_bump
    )


def test_infer_bump_exits_when_only_gitkeep_is_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bump_version = _load_bump_version()
    changelog_dir = _changelog_dir(tmp_path, ".gitkeep")

    with pytest.raises(SystemExit) as exit_info:
        bump_version.infer_bump(changelog_dir)

    assert exit_info.value.code == 1
    assert capsys.readouterr().err == "No changelog fragments found\n"
