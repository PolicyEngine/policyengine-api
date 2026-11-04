"""Check that a pull request's description names its tracking issue.

Rule api.process.pr-tracking-issue: the first line of every pull request's
description is ``Fixes #ISSUE_NUMBER``, and ISSUE_NUMBER is an open issue, not a
pull request, in this repository. The "PR description" job in
.github/workflows/pr-description.yml runs this script; it prints one error
annotation and exits 1 when the rule is broken.

Environment:
  GITHUB_EVENT_PATH  the pull_request event payload, which holds the
                     description (set by the GitHub Actions runner)
  GITHUB_REPOSITORY  owner/name of this repository (set by the runner)
  GH_TOKEN           read by gh, not by this script; the workflow sets it to
                     the job's github.token, which needs only issues: read

It needs only the standard library and gh, so the workflow runs it without
installing the project.

How the first line is read:

- A line ends at a CRLF, a carriage return or a line feed, as in Markdown, so
  descriptions edited in the GitHub web interface (which uses CRLF) pass.
- Trailing spaces and tabs are ignored: they don't show, and GitHub still reads
  the closing keyword.
- Leading whitespace fails. Four leading spaces make the line a Markdown code
  block, where GitHub doesn't read closing keywords, and any indent is a sign
  the line isn't what the author meant.
- An empty or missing (``null``) description fails.
- The number is ASCII digits without a leading zero.

``require_open_issue`` is the issue lookup on its own. Its errors say only what
is wrong; ``main`` adds the fix.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

RULE_ID = "api.process.pr-tracking-issue"
HOW_TO_FIX = (
    "Edit the description so its first line is exactly Fixes #ISSUE_NUMBER, "
    "where ISSUE_NUMBER is an open issue in this repository; editing the "
    "description runs this check again. See docs/engineering/skills/github-prs.md "
    f"#tracking-issues (rule {RULE_ID})."
)
RETRY_LOOKUP = (
    "Re-run this job; if it fails again, check the GH_TOKEN the workflow gives it."
)
REOPEN_ISSUE = (
    "If this pull request still fixes it, reopen it and re-run this job; "
    "otherwise open an issue for this work and edit the first line to name it "
    f"(rule {RULE_ID})."
)
FIXES_LINE = re.compile(r"Fixes #([1-9][0-9]*)")
# Markdown line endings: CRLF, a carriage return alone, or a line feed.
LINE_ENDING = re.compile(r"\r\n|\r|\n")
# How much of a rejected first line a message quotes.
SHOWN_FIRST_LINE_LENGTH = 80
# gh api's error for a number GitHub has no issue or pull request for (404),
# or one whose issue was deleted (410).
MISSING_ISSUE = re.compile(r"\(HTTP (?:404|410)\)")
# The path of an issue's repository_url: [api/v3/]repos/<owner>/<name>.
REPOSITORY_PATH = re.compile(r"(?:.+/)?repos/([^/]+/[^/]+)")
ANNOTATION_TITLE = "PR description"


class DescriptionError(Exception):
    """The description's first line does not name an issue as the rule requires."""


class IssueLookupError(Exception):
    """GitHub couldn't be asked about an issue, or its answer wasn't an issue.

    Running the lookup again may succeed. The message says what went wrong,
    without a fix.
    """


class NotAnOpenIssueError(Exception):
    """A number names no open issue in the repository.

    ``state`` is the issue's state, such as ``closed``, when the number names an
    issue in the repository that isn't open, and None when it names no issue
    there. The message says what the number names, without a fix.
    """

    def __init__(self, message: str, *, state: str | None = None) -> None:
        """Keep ``message`` as the error's text, and the issue's ``state``."""
        super().__init__(message)
        self.state = state


def _shown(line: str) -> str:
    """Return ``line`` quoted for a message, shortened when it is long."""
    if len(line) > SHOWN_FIRST_LINE_LENGTH:
        line = line[:SHOWN_FIRST_LINE_LENGTH].rstrip() + "..."
    return f'"{line}"'


def issue_number_from_description(body: str | None) -> int:
    """Return the issue number on the description's first line.

    Raise ``DescriptionError``, with a message that says how to fix the
    description, unless the first line is ``Fixes #ISSUE_NUMBER``.
    """
    if body is None or not body.strip():
        msg = f"The description is empty. {HOW_TO_FIX}"
        raise DescriptionError(msg)

    lines = [line.rstrip(" \t") for line in LINE_ENDING.split(body)]
    first_line = lines[0]
    match = FIXES_LINE.fullmatch(first_line)
    if match:
        return int(match.group(1))

    if FIXES_LINE.fullmatch(first_line.lstrip()):
        msg = (
            f"The first line starts with whitespace: {_shown(first_line)}. {HOW_TO_FIX}"
        )
        raise DescriptionError(msg)
    for line_number, line in enumerate(lines[1:], start=2):
        if FIXES_LINE.fullmatch(line.strip()):
            msg = (
                f"{line.strip()} is on line {line_number}, but it must be the "
                f"first line. {HOW_TO_FIX}"
            )
            raise DescriptionError(msg)
    msg = f"The first line is {_shown(first_line)}. {HOW_TO_FIX}"
    raise DescriptionError(msg)


def fetch_issue(repository: str, number: int) -> dict[str, object]:
    """Return GitHub's answer for issue ``number`` in ``repository``, from gh api.

    The issues API also answers for pull requests, and gh follows the redirect
    GitHub sends for an issue transferred to another repository, so the answer
    still has to be checked with ``check_issue``. Raise ``NotAnOpenIssueError``
    when GitHub has no issue ``number``, and ``IssueLookupError`` when the
    lookup fails.
    """
    completed = subprocess.run(
        ["gh", "api", f"repos/{repository}/issues/{number}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        if MISSING_ISSUE.search(completed.stderr):
            msg = f"There is no issue #{number} in {repository}."
            raise NotAnOpenIssueError(msg)
        reported = completed.stderr.strip() or f"exit status {completed.returncode}"
        msg = f"Could not look up #{number} in {repository}: {reported}."
        raise IssueLookupError(msg)
    try:
        issue = json.loads(completed.stdout)
    except json.JSONDecodeError:
        issue = None
    if not isinstance(issue, dict):
        msg = f"gh api did not print an issue for #{number}."
        raise IssueLookupError(msg)
    return issue


def _repository_of(repository_url: object) -> str | None:
    """Return ``owner/name`` from an issue's ``repository_url``, if it has one."""
    if not isinstance(repository_url, str):
        return None
    match = REPOSITORY_PATH.fullmatch(urlsplit(repository_url).path.strip("/"))
    return match.group(1) if match else None


def check_issue(repository: str, number: int, issue: dict[str, object]) -> None:
    """Return quietly if ``issue``, GitHub's answer for ``number``, is open here.

    Raise ``NotAnOpenIssueError`` when it is a pull request, an issue moved to
    another repository or an issue that isn't open, and ``IssueLookupError``
    when the answer names no repository.
    """
    issue_repository = _repository_of(issue.get("repository_url"))
    if issue_repository is None:
        msg = (
            f"GitHub's answer for #{number} names no repository, so it can't be "
            f"confirmed as an issue in {repository}."
        )
        raise IssueLookupError(msg)
    if issue_repository.lower() != repository.lower() or issue.get("number") != number:
        msg = (
            f"#{number} is not an issue in {repository}: it moved to "
            f"{issue_repository}#{issue.get('number')}."
        )
        raise NotAnOpenIssueError(msg)
    if issue.get("pull_request") is not None:
        msg = f"#{number} is a pull request, not an issue."
        raise NotAnOpenIssueError(msg)
    state = issue.get("state")
    if state != "open":
        msg = f"Issue #{number} is {state}."
        raise NotAnOpenIssueError(msg, state=str(state))


def require_open_issue(repository: str, number: int) -> None:
    """Return quietly if ``number`` is an open issue, not a pull request, here.

    Raise ``NotAnOpenIssueError`` or ``IssueLookupError`` otherwise; see
    ``fetch_issue`` and ``check_issue``.
    """
    check_issue(repository, number, fetch_issue(repository, number))


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        msg = f"{name} is required"
        raise SystemExit(msg)
    return value


def _description_from_event(event_path: str) -> str | None:
    """Return the pull request description in the event payload at ``event_path``."""
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull_request = event.get("pull_request") if isinstance(event, dict) else None
    if not isinstance(pull_request, dict):
        msg = (
            f"The event payload at {event_path} has no pull_request; run this "
            "check on pull_request events."
        )
        raise SystemExit(msg)
    body = pull_request.get("body")
    return body if isinstance(body, str) else None


def _annotation_text(message: str) -> str:
    """Escape ``message`` so the runner reads it as one annotation message."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main() -> int:
    """Check the pull request in this run's event; return the exit status."""
    repository = _required_environment("GITHUB_REPOSITORY")
    description = _description_from_event(_required_environment("GITHUB_EVENT_PATH"))
    try:
        number = issue_number_from_description(description)
        require_open_issue(repository, number)
    except DescriptionError as error:
        message = str(error)
    except IssueLookupError as error:
        message = f"{error} {RETRY_LOOKUP}"
    except NotAnOpenIssueError as error:
        message = f"{error} {HOW_TO_FIX if error.state is None else REOPEN_ISSUE}"
    else:
        print(
            f"The first line is Fixes #{number}, and #{number} is an open issue in "
            f"{repository}."
        )
        return 0
    print(f"::error title={ANNOTATION_TITLE}::{_annotation_text(message)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
