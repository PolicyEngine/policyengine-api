"""Tests for .github/changelog_fragments.py: what a changelog fragment is.

The PR check and the release's version bump both read fragments through
``FragmentDefinition`` (rule api.process.changelog-fragment), so these cases
pin down what both of them accept.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.unit.changelog_fragment_support import REPO, changelog_fragments

if TYPE_CHECKING:
    from pathlib import Path

fragments_module = changelog_fragments()

CONFIGURED_TYPES = ("breaking", "added", "changed", "fixed", "removed")
LISTED_TYPES = "breaking, added, changed, fixed or removed"
RULE_FIXTURES = REPO / "rules/fixtures/api.process.changelog-fragment"
# The fragment #4084 added, and the text #4106 moved to changelog.d/.
PULL_REQUEST_4084_FRAGMENT = "changelog.d/added/4083.md"
FRAGMENT_TEXT = "Report when the deployed version went live.\n"
EMPTY_ENTRY = (
    "Write a sentence or two in it saying what changed: Towncrier would "
    "publish an empty entry."
)
FORM_TERMS = (
    f"<type> is {LISTED_TYPES}, and <name> is letters and digits, in groups "
    "joined by single dots, hyphens or underscores"
)
INVISIBLE_ONLY = (
    "holds no visible text, only invisible characters such as zero-width spaces."
)
GENERIC_RENAME = f"Rename it to changelog.d/<name>.<type>.md, where {FORM_TERMS}."


def _definition():
    return fragments_module.FragmentDefinition.load(REPO)


def _write(root: Path, relative_path: str, text: str) -> Path:
    file_path = root / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(text, encoding="utf-8")
    return file_path


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Return a root holding the repository's pyproject.toml and changelog.d/."""
    (tmp_path / "pyproject.toml").write_text(
        (REPO / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _write(tmp_path, "changelog.d/.gitkeep", "")
    return tmp_path


def _towncrier_config(directory: str, *type_directories: str) -> str:
    type_tables = "".join(
        f'\n[[tool.towncrier.type]]\ndirectory = "{type_directory}"\n'
        f'name = "{type_directory.title()}"\n'
        for type_directory in type_directories
    )
    return f'[tool.towncrier]\ndirectory = "{directory}"\n{type_tables}'


def test_the_directory_and_types_come_from_tool_towncrier_in_pyproject():
    definition = _definition()

    assert definition.directory == "changelog.d"
    assert definition.types == CONFIGURED_TYPES


def test_the_types_are_read_from_the_given_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        _towncrier_config("notes", "added", "security"), encoding="utf-8"
    )

    definition = fragments_module.FragmentDefinition.load(tmp_path)

    assert definition.directory == "notes"
    assert definition.types == ("added", "security")


@pytest.mark.parametrize(
    ("config", "expected_error"),
    [
        ('[project]\nname = "x"\n', "Could not read the fragment directory"),
        ('[tool.towncrier]\ndirectory = "changelog.d"\n', "Could not read"),
        (
            '[tool.towncrier]\ndirectory = "changelog.d"\ntype = []\n',
            "must list each fragment type once",
        ),
        (
            _towncrier_config("changelog.d", "added", "added"),
            "must list each fragment type once",
        ),
        (_towncrier_config("notes/changelog.d", "added"), "is not one folder"),
        (_towncrier_config("../changelog.d", "added"), "is not one folder"),
        (_towncrier_config("changelog.d", "Added"), 'type "Added"'),
        (_towncrier_config("changelog.d", "md"), 'type "md"'),
    ],
    ids=[
        "no-towncrier-table",
        "no-types",
        "empty-type-list",
        "duplicate-type",
        "nested-directory",
        "parent-directory",
        "uppercase-type",
        "extension-as-type",
    ],
)
def test_load_refuses_a_configuration_the_release_cannot_follow(
    tmp_path: Path, config: str, expected_error: str
):
    (tmp_path / "pyproject.toml").write_text(config, encoding="utf-8")

    with pytest.raises(fragments_module.ConfigurationError, match=expected_error):
        fragments_module.FragmentDefinition.load(tmp_path)


@pytest.mark.parametrize(
    ("file_name", "expected_name", "expected_type"),
    [
        ("4083.added.md", "4083", "added"),
        ("report-live-since.added.md", "report-live-since", "added"),
        ("relock-dependencies.changed.md", "relock-dependencies", "changed"),
        (
            "update-policyengine-bundle-6.11.1.changed.md",
            "update-policyengine-bundle-6.11.1",
            "changed",
        ),
        ("v2_reports.breaking.md", "v2_reports", "breaking"),
        ("fixed.removed.md", "fixed", "removed"),
    ],
)
def test_a_file_named_name_type_md_directly_in_changelog_d_is_a_fragment(
    repository: Path, file_name: str, expected_name: str, expected_type: str
):
    _write(repository, f"changelog.d/{file_name}", FRAGMENT_TEXT)

    scan = _definition().scan(repository)

    assert scan.problems == {}
    assert scan.fragments == (
        fragments_module.Fragment(
            path=f"changelog.d/{file_name}",
            name=expected_name,
            fragment_type=expected_type,
        ),
    )


def test_pull_request_4084s_fragment_in_a_type_folder_is_not_a_fragment(
    repository: Path,
):
    _write(repository, PULL_REQUEST_4084_FRAGMENT, FRAGMENT_TEXT)

    scan = _definition().scan(repository)

    assert scan.fragments == ()
    assert scan.problems == {
        PULL_REQUEST_4084_FRAGMENT: (
            "changelog.d/added/4083.md is in a folder inside changelog.d/. The "
            "release reads only files directly in changelog.d/ and stops at "
            "anything else there. Move it to changelog.d/4083.added.md."
        )
    }


@pytest.mark.parametrize(
    ("relative_path", "expected_problem"),
    [
        (
            "changelog.d/fixed/4083.fixed.md",
            "is in a folder inside changelog.d/. The release reads only files "
            "directly in changelog.d/ and stops at anything else there. Move it "
            "to changelog.d/4083.fixed.md.",
        ),
        (
            "changelog.d/notes/today.txt",
            f"Move it to changelog.d/<name>.<type>.md, where {FORM_TERMS}, or "
            "delete it.",
        ),
        (
            "changelog.d/added/.gitkeep",
            "changelog.d/added/.gitkeep is in a folder inside changelog.d/.",
        ),
    ],
)
def test_every_file_in_a_folder_inside_changelog_d_is_a_problem(
    repository: Path, relative_path: str, expected_problem: str
):
    _write(repository, relative_path, FRAGMENT_TEXT)

    scan = _definition().scan(repository)

    assert scan.fragments == ()
    assert list(scan.problems) == [relative_path]
    assert expected_problem in scan.problems[relative_path]


def test_empty_folders_are_listed_apart_from_the_problems(repository: Path):
    """Git can't commit an empty folder, so one is in a checkout only by accident.

    A local ``git mv`` out of changelog.d/added/ leaves one behind; in a fresh
    checkout, only a submodule makes one. The version bump treats each as a
    problem, as Towncrier does; the PR check reports one only if the pull
    request changed that path.
    """
    (repository / "changelog.d/added").mkdir()
    (repository / "changelog.d/notes/drafts").mkdir(parents=True)

    definition = _definition()
    scan = definition.scan(repository)

    assert scan.problems == {}
    assert scan.empty_folders == ("changelog.d/added", "changelog.d/notes/drafts")
    assert definition.empty_folder_problem("changelog.d/added") == (
        "changelog.d/added is an empty folder or a submodule inside changelog.d/. "
        "The release reads only files directly in changelog.d/ and stops at "
        "anything else there. Delete it."
    )


@pytest.mark.parametrize(
    ("file_name", "expected_problem"),
    [
        (
            "4083.feature.md",
            'changelog.d/4083.feature.md has the type "feature", which is not '
            "one of the types in [tool.towncrier] in pyproject.toml: "
            f"{LISTED_TYPES}. Rename it to changelog.d/4083.<type>.md with one "
            "of those types.",
        ),
        (
            "4083.Added.md",
            'changelog.d/4083.Added.md has the type "Added", but types are '
            "lowercase. Rename it to changelog.d/4083.added.md.",
        ),
        (
            "4083.added.extra.md",
            'changelog.d/4083.added.extra.md has the type "extra", which is not '
            "one of the types",
        ),
    ],
)
def test_a_fragment_with_an_unknown_type_is_a_problem(
    repository: Path, file_name: str, expected_problem: str
):
    _write(repository, f"changelog.d/{file_name}", FRAGMENT_TEXT)

    scan = _definition().scan(repository)

    assert scan.fragments == ()
    assert expected_problem in scan.problems[f"changelog.d/{file_name}"]


@pytest.mark.parametrize(
    ("file_name", "expected_fix"),
    [
        ("notes.md", GENERIC_RENAME),
        ("4083.added", "Rename it to changelog.d/4083.added.md."),
        ("4083.added.rst", "Rename it to changelog.d/4083.added.md."),
        ("4083.added.MD", "Rename it to changelog.d/4083.added.md."),
        ("4083.added.md ", "Rename it to changelog.d/4083.added.md."),
        (".added.md", GENERIC_RENAME),
        ("added.md", GENERIC_RENAME),
        ("fix login.added.md", GENERIC_RENAME),
        ("4083..added.md", GENERIC_RENAME),
        ("-4083.added.md", GENERIC_RENAME),
    ],
)
def test_a_file_not_named_name_type_md_is_a_problem(
    repository: Path, file_name: str, expected_fix: str
):
    relative_path = f"changelog.d/{file_name}"
    _write(repository, relative_path, FRAGMENT_TEXT)

    scan = _definition().scan(repository)

    assert scan.fragments == ()
    problem = scan.problems[relative_path]
    assert problem.startswith(
        f"{relative_path} is not named <name>.<type>.md: its file name is "
        f"{file_name!r}. The release can't read it."
    )
    assert problem.endswith(expected_fix)


@pytest.mark.parametrize(
    ("text", "expected_problem"),
    [
        ("", f"changelog.d/4083.added.md is empty. {EMPTY_ENTRY}"),
        (
            " \n\t\n",
            f"changelog.d/4083.added.md holds only whitespace. {EMPTY_ENTRY}",
        ),
        (
            "\ufeff\n",
            f"changelog.d/4083.added.md holds only whitespace. {EMPTY_ENTRY}",
        ),
        ("\u200b\n", f"changelog.d/4083.added.md {INVISIBLE_ONLY} {EMPTY_ENTRY}"),
        (
            "\ufeff\u2060\u200d \u00ad\n",
            f"changelog.d/4083.added.md {INVISIBLE_ONLY} {EMPTY_ENTRY}",
        ),
    ],
    ids=[
        "empty",
        "whitespace-only",
        "byte-order-mark-only",
        "zero-width-space-only",
        "format-characters-only",
    ],
)
def test_a_fragment_without_text_is_a_problem(
    repository: Path, text: str, expected_problem: str
):
    _write(repository, "changelog.d/4083.added.md", text)

    scan = _definition().scan(repository)

    assert scan.fragments == ()
    assert scan.problems == {"changelog.d/4083.added.md": expected_problem}


@pytest.mark.parametrize(
    "text", ["\u200bFixed.\n", "\u00e9\n", "\u2014\n", "7\n", "\u4e2d\u6587\n"]
)
def test_a_fragment_with_any_visible_character_is_read(repository: Path, text: str):
    _write(repository, "changelog.d/4083.added.md", text)

    scan = _definition().scan(repository)

    assert scan.problems == {}
    assert [fragment.path for fragment in scan.fragments] == [
        "changelog.d/4083.added.md"
    ]


def test_a_fragment_that_is_not_utf8_is_a_problem(repository: Path):
    (repository / "changelog.d/4083.added.md").write_bytes(b"caf\xe9\n")

    scan = _definition().scan(repository)

    assert scan.problems == {
        "changelog.d/4083.added.md": (
            "changelog.d/4083.added.md is not UTF-8 text. Save it as UTF-8."
        )
    }


@pytest.mark.parametrize(
    "link_target", ["../pyproject.toml", "missing.md"], ids=["file", "dangling"]
)
def test_a_symbolic_link_is_not_a_fragment(repository: Path, link_target: str):
    (repository / "changelog.d/4083.added.md").symlink_to(link_target)

    scan = _definition().scan(repository)

    assert scan.fragments == ()
    assert scan.problems == {
        "changelog.d/4083.added.md": (
            "changelog.d/4083.added.md is a symbolic link. A fragment is a "
            "regular file that holds its text; replace the link with one."
        )
    }


def test_a_symbolic_link_to_a_folder_is_not_a_fragment(repository: Path):
    (repository / "elsewhere").mkdir()
    _write(repository, "elsewhere/4083.added.md", FRAGMENT_TEXT)
    (repository / "changelog.d/added").symlink_to("../elsewhere")

    scan = _definition().scan(repository)

    assert scan.fragments == ()
    assert list(scan.problems) == ["changelog.d/added"]
    assert "is a symbolic link" in scan.problems["changelog.d/added"]


def test_gitkeep_is_the_only_other_file_allowed_and_must_be_a_regular_file(
    repository: Path,
):
    _write(repository, "changelog.d/4083.added.md", FRAGMENT_TEXT)

    assert _definition().scan(repository).problems == {}

    (repository / "changelog.d/.gitkeep").unlink()
    (repository / "changelog.d/.gitkeep").symlink_to("4083.added.md")

    assert list(_definition().scan(repository).problems) == ["changelog.d/.gitkeep"]


def test_a_missing_fragment_directory_holds_no_fragments(tmp_path: Path):
    scan = _definition().scan(tmp_path)

    assert scan.fragments == ()
    assert scan.problems == {}


def test_a_fragment_directory_that_is_a_file_is_a_problem(tmp_path: Path):
    (tmp_path / "changelog.d").write_text(FRAGMENT_TEXT, encoding="utf-8")

    scan = _definition().scan(tmp_path)

    assert scan.fragments == ()
    assert scan.problems == {
        "changelog.d": (
            "changelog.d is not a folder. The release reads fragments from the "
            "folder changelog.d/; make it one."
        )
    }


def test_scan_lists_fragments_and_problems_in_path_order(repository: Path):
    _write(repository, "changelog.d/b.fixed.md", FRAGMENT_TEXT)
    _write(repository, "changelog.d/a.added.md", FRAGMENT_TEXT)
    _write(repository, PULL_REQUEST_4084_FRAGMENT, FRAGMENT_TEXT)
    _write(repository, "changelog.d/z.feature.md", FRAGMENT_TEXT)

    scan = _definition().scan(repository)

    assert [fragment.path for fragment in scan.fragments] == [
        "changelog.d/a.added.md",
        "changelog.d/b.fixed.md",
    ]
    assert list(scan.problems) == [
        PULL_REQUEST_4084_FRAGMENT,
        "changelog.d/z.feature.md",
    ]


def test_the_accepted_form_names_the_directory_types_and_documentation():
    assert _definition().accepted_form() == (
        "Add a file changelog.d/<name>.<type>.md, directly in changelog.d/, "
        "that says in a sentence or two what changed for people who use or "
        f"run the Public API. {FORM_TERMS}, such as an issue number. See "
        "docs/engineering/skills/github-prs.md#changelog-fragments (rule "
        "api.process.changelog-fragment)."
    )


def test_rule_proof_changelog_fragment():
    """The definition rejects #4084's fragment and accepts #4106's rename of it."""
    definition = _definition()

    bad_scan = definition.scan(RULE_FIXTURES / "bad")
    good_scan = definition.scan(RULE_FIXTURES / "good")

    assert bad_scan.fragments == ()
    assert list(bad_scan.problems) == [PULL_REQUEST_4084_FRAGMENT]
    assert good_scan.problems == {}
    assert [fragment.path for fragment in good_scan.fragments] == [
        "changelog.d/report-live-since.added.md"
    ]
