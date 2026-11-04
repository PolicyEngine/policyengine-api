"""Tests for .github/scripts/close_bundle_update_issue.sh and its workflow.

Each PolicyEngine bundle-update pull request names an issue of its own on the
first line of its description (rule api.process.pr-tracking-issue). Merging
the pull request closes that issue; when the pull request is closed without
merging, as superseded updates are, close-bundle-update-issue.yml runs the
script to close it. A fake ``gh`` first on PATH records the calls and answers
the issue lookup, so no test reaches GitHub.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github" / "scripts" / "close_bundle_update_issue.sh"
WORKFLOW = REPO / ".github" / "workflows" / "close-bundle-update-issue.yml"
JOB = "close-tracking-issue"
REPOSITORY = "PolicyEngine/policyengine-api"
BRANCH = "auto/update-policyengine-bundle-6.12.1"
ISSUE_TITLE = "Update PolicyEngine bundle to 6.12.1"
DESCRIPTION = "Fixes #4320\n\n## Summary\n\nUpdate PolicyEngine .py bundle.\n"

# Records its arguments; for gh api, prints FAKE_GH_ISSUE, or fails when
# FAKE_GH_API_FAIL is set.
FAKE_GH = f"""#!{sys.executable}
import json
import os
import sys

arguments = sys.argv[1:]
with open(os.environ["FAKE_GH_CALLS"], "a", encoding="utf-8") as calls:
    calls.write(json.dumps(["gh", *arguments]) + "\\n")
if arguments[:1] == ["api"]:
    if os.environ.get("FAKE_GH_API_FAIL"):
        sys.stderr.write("gh: Bad credentials (HTTP 401)\\n")
        sys.exit(1)
    sys.stdout.write(os.environ.get("FAKE_GH_ISSUE", "{{}}"))
"""


def _issue(
    number: int = 4320, *, title: str = ISSUE_TITLE, state: str = "open", **fields
) -> dict:
    return {"number": number, "title": title, "state": state, **fields}


def _event(
    *,
    body: str | None = DESCRIPTION,
    branch: str = BRANCH,
    merged: bool = False,
) -> dict:
    return {
        "action": "closed",
        "number": 4163,
        "pull_request": {
            "number": 4163,
            "state": "closed",
            "merged": merged,
            "body": body,
            "head": {"ref": branch, "repo": {"full_name": REPOSITORY}},
        },
    }


def _close(
    tmp_path: Path, event: dict, issue: dict | None = None, **environment: str
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """Run the script on ``event``; return the result and the gh calls."""
    binaries = tmp_path / "bin"
    binaries.mkdir(exist_ok=True)
    fake_gh = binaries / "gh"
    fake_gh.write_text(FAKE_GH, encoding="utf-8")
    fake_gh.chmod(0o755)
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    calls_log = tmp_path / "gh-calls.jsonl"
    run_environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GITHUB_", "FAKE_GH_", "GH_"))
    }
    run_environment.update(
        {
            "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GH_CALLS": str(calls_log),
            "FAKE_GH_ISSUE": json.dumps(issue if issue is not None else _issue()),
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_REPOSITORY": REPOSITORY,
            **environment,
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)],
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


def _closes(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if call[1:3] == ["issue", "close"]]


# --- Closing the issue ----------------------------------------------------


def test_closes_the_issue_an_unmerged_bundle_update_names(tmp_path):
    result, calls = _close(tmp_path, _event())

    assert result.returncode == 0, result.stderr
    assert calls[0] == ["gh", "api", f"repos/{REPOSITORY}/issues/4320"]
    (close,) = _closes(calls)
    assert close[:4] == ["gh", "issue", "close", "4320"]
    assert close[close.index("--repo") + 1] == REPOSITORY
    assert close[close.index("--reason") + 1] == "not planned"
    assert "#4163 was closed without merging" in close[close.index("--comment") + 1]
    assert "Closed issue #4320" in result.stdout


def test_a_crlf_description_names_the_issue_too(tmp_path):
    result, calls = _close(tmp_path, _event(body="Fixes #4320 \r\n\r\n## Summary\r\n"))

    assert result.returncode == 0, result.stderr
    assert len(_closes(calls)) == 1


# --- Leaving the issue alone ----------------------------------------------


@pytest.mark.parametrize(
    "event",
    [
        # Merging closed the issue through the Fixes line.
        _event(merged=True),
        # Not a bundle-update pull request.
        _event(branch="pr-description-check"),
        _event(branch="auto/relock-dependencies"),
    ],
)
def test_other_closed_pull_requests_are_left_alone(tmp_path, event):
    result, calls = _close(tmp_path, event)

    assert result.returncode == 0, result.stderr
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [None, "", "## Summary\n\nUpdate PolicyEngine .py bundle.\n", "Fixes #4320."],
)
def test_a_description_without_a_fixes_first_line_closes_nothing(tmp_path, body):
    result, calls = _close(tmp_path, _event(body=body))

    assert result.returncode == 0, result.stderr
    assert "names no tracking issue" in result.stdout
    assert calls == []


@pytest.mark.parametrize(
    ("issue", "expected_message"),
    [
        # Someone edited the line to name another version's issue.
        (
            _issue(title="Update PolicyEngine bundle to 6.13.0"),
            'is titled "Update PolicyEngine bundle to 6.13.0"',
        ),
        (_issue(title="Relock dependencies"), 'is titled "Relock dependencies"'),
        (_issue(state="closed"), "is already closed"),
        (
            _issue(pull_request={"url": "https://api.github.com/pulls/4320"}),
            "is a pull request",
        ),
    ],
)
def test_an_issue_that_isnt_this_versions_open_issue_is_left_open(
    tmp_path, issue, expected_message
):
    result, calls = _close(tmp_path, _event(), issue)

    assert result.returncode == 0, result.stderr
    assert expected_message in result.stdout
    assert _closes(calls) == []


# --- Failures -------------------------------------------------------------


def test_a_failed_issue_lookup_fails_and_closes_nothing(tmp_path):
    result, calls = _close(tmp_path, _event(), FAKE_GH_API_FAIL="1")

    assert result.returncode != 0
    assert "Could not look up issue #4320" in result.stderr
    assert _closes(calls) == []


@pytest.mark.parametrize("variable", ["GITHUB_EVENT_PATH", "GITHUB_REPOSITORY"])
def test_the_script_requires_its_environment(tmp_path, variable):
    result, calls = _close(tmp_path, _event(), **{variable: ""})

    assert result.returncode != 0
    assert f"{variable} is required" in result.stderr
    assert calls == []


# --- The workflow ---------------------------------------------------------


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_runs_when_a_pull_request_closes_even_with_conflicts(
    workflow,
):
    """pull_request workflows don't run while a pull request has a conflict.

    A superseded bundle update usually conflicts with master, because the
    newer one that merged changed the same pins, so the workflow listens for
    pull_request_target, which GitHub runs anyway, from the default branch.
    """
    # PyYAML reads the key "on" as True.
    assert workflow.get("on", workflow.get(True)) == {
        "pull_request_target": {"types": ["closed"]}
    }


def test_the_job_runs_only_for_unmerged_bundle_updates_from_this_repository(
    workflow,
):
    assert list(workflow["jobs"]) == [JOB]
    assert workflow["jobs"][JOB]["if"] == (
        "${{ !github.event.pull_request.merged"
        " && startsWith(github.event.pull_request.head.ref,"
        " 'auto/update-policyengine-bundle-')"
        " && github.event.pull_request.head.repo.full_name == github.repository }}"
    )


def test_the_job_token_can_write_issues_and_only_read_the_rest(workflow):
    # gh issue close looks the number up as an issue or a pull request.
    assert workflow["permissions"] == {
        "contents": "read",
        "issues": "write",
        "pull-requests": "read",
    }
    assert "permissions" not in workflow["jobs"][JOB]


def test_the_job_runs_the_tested_script_with_the_job_token(workflow):
    steps = workflow["jobs"][JOB]["steps"]
    checkout = next(
        step for step in steps if step.get("uses", "").startswith("actions/checkout@")
    )
    script_steps = [step for step in steps if SCRIPT.name in step.get("run", "")]

    assert checkout["with"]["sparse-checkout"] == f".github/scripts/{SCRIPT.name}"
    # pull_request_target checks out the default branch unless told otherwise;
    # the job must never run the pull request's code with a token that writes.
    assert "ref" not in checkout["with"]
    assert "repository" not in checkout["with"]
    assert len(script_steps) == 1
    assert script_steps[0]["run"] == f"bash .github/scripts/{SCRIPT.name}"
    assert script_steps[0]["env"] == {"GH_TOKEN": "${{ github.token }}"}
