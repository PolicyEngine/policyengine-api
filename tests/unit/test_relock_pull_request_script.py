"""Tests for .github/scripts/open_relock_pull_request.sh.

Each test builds a temporary git repository whose ``origin`` is a local bare
repository, so pushes are real but stay on disk. A fake ``gh`` records its
calls and answers the pull-request and issue lookups.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github/scripts/open_relock_pull_request.sh"
RELOCK_BRANCH = "auto/relock-dependencies"
FRAGMENT = "changelog.d/relock-dependencies.changed.md"
ISSUE_URL = "https://github.com/PolicyEngine/policyengine-api/issues/77"
SUMMARY = "## Version changes\n\n- `numpy`: 2.3.0 → 2.3.1\n"

FAKE_GH = f"""#!{sys.executable}
import json
import os
import sys

arguments = sys.argv[1:]
body = sys.stdin.read() if "--body-file" in arguments else None
with open(os.environ["RELOCK_TEST_CALLS"], "a") as calls:
    calls.write(json.dumps({{"arguments": ["gh", *arguments], "body": body}}) + "\\n")
if arguments[:2] == ["pr", "list"]:
    print(os.environ.get("RELOCK_TEST_OPEN_PR", ""))
elif arguments[:2] == ["issue", "list"]:
    if os.environ.get("RELOCK_TEST_ISSUE_LIST_EXIT"):
        sys.exit(1)
    print(os.environ.get("RELOCK_TEST_OPEN_ISSUE", ""))
elif arguments[:2] == ["issue", "create"]:
    print("{ISSUE_URL}")
"""


def _git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=directory,
        env=_git_environment(),
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _git_environment() -> dict[str, str]:
    """Return an environment that ignores the user's and system git settings."""
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """Return a master checkout with a relocked uv.lock and a local origin."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=master", str(origin))
    repository = tmp_path / "checkout"
    repository.mkdir()
    _git(repository, "init", "--quiet", "--initial-branch=master")
    (repository / "changelog.d").mkdir()
    (repository / "changelog.d/.gitkeep").write_text("")
    (repository / "uv.lock").write_text('version = 1\nname = "numpy-2.3.0"\n')
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", "Initial commit")
    _git(repository, "remote", "add", "origin", str(origin))
    _git(repository, "push", "--quiet", "origin", "master")
    (repository / "uv.lock").write_text('version = 1\nname = "numpy-2.3.1"\n')
    return repository


def _open_pull_request(
    repository: Path, **environment: str
) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    """Run the script with a fake gh; return the result and the gh calls."""
    binaries = repository.parent / "bin"
    binaries.mkdir(exist_ok=True)
    fake_gh = binaries / "gh"
    fake_gh.write_text(FAKE_GH)
    fake_gh.chmod(0o755)
    summary = repository.parent / "summary.md"
    summary.write_text(SUMMARY)
    calls_log = repository.parent / "gh-calls.jsonl"
    calls_log.unlink(missing_ok=True)
    run_environment = {
        **_git_environment(),
        "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "PolicyEngine/policyengine-api",
        "RELOCK_SUMMARY_FILE": str(summary),
        "RELOCK_TEST_CALLS": str(calls_log),
    }
    for name in ("BASE_BRANCH", "RELOCK_BRANCH"):
        run_environment.pop(name, None)
    run_environment.update(environment)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=repository,
        env=run_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    calls = (
        [json.loads(call) for call in calls_log.read_text().splitlines()]
        if calls_log.exists()
        else []
    )
    return result, calls


def _calls_to(calls: list[dict], *command: str) -> list[dict]:
    return [call for call in calls if call["arguments"][1:3] == list(command)]


def _remote_branch(repository: Path, branch: str = RELOCK_BRANCH) -> str:
    return _git(repository, "ls-remote", "--heads", "origin", f"refs/heads/{branch}")


def test_opens_a_pull_request_naming_a_new_tracking_issue(checkout: Path) -> None:
    result, calls = _open_pull_request(checkout)

    assert result.returncode == 0, result.stderr
    pushed = _remote_branch(checkout).split()[0]
    assert _git(checkout, "show", f"{pushed}:uv.lock").endswith('"numpy-2.3.1"')
    assert _git(checkout, "show", f"{pushed}:{FRAGMENT}")
    assert _git(checkout, "rev-parse", f"{pushed}^") == _git(
        checkout, "rev-parse", "origin/master"
    )
    (created_issue,) = _calls_to(calls, "issue", "create")
    assert "Relock dependencies" in created_issue["arguments"]
    (created_pr,) = _calls_to(calls, "pr", "create")
    arguments = created_pr["arguments"]
    assert arguments[arguments.index("--base") + 1] == "master"
    assert arguments[arguments.index("--head") + 1] == RELOCK_BRANCH
    assert arguments[arguments.index("--title") + 1] == "Relock dependencies"
    assert created_pr["body"].splitlines()[0] == "Fixes #77"
    assert SUMMARY in created_pr["body"]
    assert not _calls_to(calls, "pr", "edit")


def test_the_pull_request_adds_a_fragment_the_release_reads(checkout: Path) -> None:
    from tests.unit.changelog_fragment_support import changelog_fragments

    result, _ = _open_pull_request(checkout)

    assert result.returncode == 0, result.stderr
    pushed = _remote_branch(checkout).split()[0]
    added_paths = _git(
        checkout, "diff", "--name-only", "--diff-filter=A", "origin/master", pushed
    ).splitlines()
    assert added_paths == [FRAGMENT]
    pushed_fragment = checkout.parent / "pushed-fragment.md"
    pushed_fragment.write_text(_git(checkout, "show", f"{pushed}:{FRAGMENT}") + "\n")
    definition = changelog_fragments().FragmentDefinition.load(REPO)
    assert definition.problem_with(FRAGMENT, pushed_fragment) is None


def test_reuses_the_open_tracking_issue(checkout: Path) -> None:
    result, calls = _open_pull_request(checkout, RELOCK_TEST_OPEN_ISSUE="41")

    assert result.returncode == 0, result.stderr
    (issue_lookup,) = _calls_to(calls, "issue", "list")
    assert any('"Relock dependencies"' in part for part in issue_lookup["arguments"])
    assert not _calls_to(calls, "issue", "create")
    (created_pr,) = _calls_to(calls, "pr", "create")
    assert created_pr["body"].splitlines()[0] == "Fixes #41"


def test_updates_the_open_pull_request_instead_of_opening_another(
    checkout: Path,
) -> None:
    first_result, _ = _open_pull_request(checkout, RELOCK_TEST_OPEN_ISSUE="41")
    assert first_result.returncode == 0, first_result.stderr
    first_push = _remote_branch(checkout).split()[0]
    _git(checkout, "checkout", "--quiet", "master")
    (checkout / "uv.lock").write_text('version = 1\nname = "numpy-2.4.0"\n')

    result, calls = _open_pull_request(
        checkout, RELOCK_TEST_OPEN_PR="12", RELOCK_TEST_OPEN_ISSUE="41"
    )

    assert result.returncode == 0, result.stderr
    pushed = _remote_branch(checkout).split()[0]
    assert pushed != first_push
    assert _git(checkout, "show", f"{pushed}:uv.lock").endswith('"numpy-2.4.0"')
    assert _git(checkout, "rev-parse", f"{pushed}^") == _git(
        checkout, "rev-parse", "origin/master"
    )
    assert not _calls_to(calls, "pr", "create")
    (edited_pr,) = _calls_to(calls, "pr", "edit")
    assert edited_pr["arguments"][3] == "12"
    assert edited_pr["body"].splitlines()[0] == "Fixes #41"


def test_does_not_push_when_the_branch_already_holds_this_relock(
    checkout: Path,
) -> None:
    first_result, _ = _open_pull_request(checkout, RELOCK_TEST_OPEN_ISSUE="41")
    assert first_result.returncode == 0, first_result.stderr
    first_push = _remote_branch(checkout)
    _git(checkout, "checkout", "--quiet", "master")
    (checkout / "uv.lock").write_text('version = 1\nname = "numpy-2.3.1"\n')

    result, calls = _open_pull_request(
        checkout, RELOCK_TEST_OPEN_PR="12", RELOCK_TEST_OPEN_ISSUE="41"
    )

    assert result.returncode == 0, result.stderr
    assert _remote_branch(checkout) == first_push
    assert "already holds this relock" in result.stdout
    assert len(_calls_to(calls, "pr", "edit")) == 1


def test_fails_before_pushing_when_the_issue_lookup_fails(checkout: Path) -> None:
    result, calls = _open_pull_request(checkout, RELOCK_TEST_ISSUE_LIST_EXIT="1")

    assert result.returncode != 0
    assert _calls_to(calls, "issue", "list")
    assert _remote_branch(checkout) == ""
    assert not _calls_to(calls, "issue", "create")
    assert not _calls_to(calls, "pr", "create")


def test_uses_the_base_and_relock_branches_it_is_given(checkout: Path) -> None:
    _git(checkout, "push", "--quiet", "origin", "master:feature")
    feature_relock = "auto/relock-dependencies-feature"

    result, calls = _open_pull_request(
        checkout, BASE_BRANCH="feature", RELOCK_BRANCH=feature_relock
    )

    assert result.returncode == 0, result.stderr
    assert _remote_branch(checkout, feature_relock)
    assert _remote_branch(checkout) == ""
    (pr_lookup,) = _calls_to(calls, "pr", "list")
    lookup = pr_lookup["arguments"]
    assert lookup[lookup.index("--base") + 1] == "feature"
    assert lookup[lookup.index("--head") + 1] == feature_relock
    (created_pr,) = _calls_to(calls, "pr", "create")
    arguments = created_pr["arguments"]
    assert arguments[arguments.index("--base") + 1] == "feature"
    assert arguments[arguments.index("--head") + 1] == feature_relock


def test_fails_before_any_change_without_the_summary(checkout: Path) -> None:
    missing_summary = str(checkout.parent / "missing-summary.md")

    result, calls = _open_pull_request(checkout, RELOCK_SUMMARY_FILE=missing_summary)

    assert result.returncode != 0
    assert "missing-summary.md" in result.stderr
    assert calls == []
    assert _remote_branch(checkout) == ""


def test_ignores_pull_requests_from_forks_with_the_same_branch_name(
    checkout: Path,
) -> None:
    result, calls = _open_pull_request(checkout, RELOCK_TEST_OPEN_ISSUE="41")

    assert result.returncode == 0, result.stderr
    (pr_lookup,) = _calls_to(calls, "pr", "list")
    lookup = pr_lookup["arguments"]
    assert "isCrossRepository" in lookup[lookup.index("--json") + 1]
    assert lookup[lookup.index("--jq") + 1] == (
        "map(select(.isCrossRepository | not)) | .[0].number // empty"
    )
