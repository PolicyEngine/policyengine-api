"""Create, update and reopen one GitHub issue per production error group."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

from telemetry_error_issues.github_client import GitHubClient, GitHubLabelError
from telemetry_error_issues.records import FINGERPRINT_ALGORITHM
from telemetry_error_issues.rendering import (
    ISSUE_TITLE_PREFIX,
    SECTION_END,
    SECTION_START,
    eastern_time,
    issue_body,
    issue_section,
    issue_title,
    parse_state,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from telemetry_error_issues.groups import ErrorGroup
    from telemetry_error_issues.log_source import LogSource
    from telemetry_error_issues.window import ReportingWindow

BOT_LOGIN = "github-actions[bot]"
TITLE_FINGERPRINT = re.compile(r"\(([0-9a-f]{16})\)$")
BASE_LABEL = "telemetry-error"
REGRESSION_LABEL = "regression"
SERVICE_LABEL_PREFIX = "service: "
MAX_LABEL_LENGTH = 50
LABEL_DETAILS = {
    BASE_LABEL: ("b60205", "Opened by the daily telemetry error report"),
    REGRESSION_LABEL: ("d93f0b", "An error that returned after its issue was closed"),
}
SERVICE_LABEL_DETAILS = ("1d76db", "Service that produced a telemetry error group")
# A production group opens an issue only when it fails this often, in this many
# distinct requests, during the window; the same thresholds reopen an issue.
MIN_PRODUCTION_OCCURRENCES = 3
MIN_PRODUCTION_REQUESTS = 2
MAX_NEW_ISSUES_PER_RUN = 5
# Failures in the first day after an issue is closed may come from code that
# hasn't been deployed yet, so they never reopen it.
REOPEN_DELAY = timedelta(hours=24)
REOPENABLE_CLOSE_REASONS = frozenset({None, "completed"})


class SyncAction(NamedTuple):
    """What one run did, or in a dry run would do, for one error group."""

    fingerprint: str
    kind: str
    family: str
    production_occurrences: int
    staging_occurrences: int
    issue_number: int | None
    action: str


class SyncResult(NamedTuple):
    """Every group's action, and how many new issues waited for a later run."""

    actions: list[SyncAction]
    deferred: int


def replace_section(body: str, section: str) -> str:
    """Replace the marked section of ``body``, or add it at the end if missing."""
    start = body.find(SECTION_START)
    end = body.find(SECTION_END, start) if start >= 0 else -1
    if end >= 0:
        return f"{body[:start]}{section}{body[end + len(SECTION_END) :]}"
    kept = body.rstrip()
    return f"{kept}\n\n{section}\n" if kept else f"{section}\n"


def _issue_fingerprint(issue: Mapping[str, Any]) -> str | None:
    """Return the fingerprint from the state comment, or else from the title."""
    state = parse_state(issue.get("body") or "")
    if state and state.get("algorithm") == FINGERPRINT_ALGORITHM:
        fingerprint_value = state.get("fingerprint")
        if isinstance(fingerprint_value, str):
            return fingerprint_value
    title = issue.get("title") or ""
    match = TITLE_FINGERPRINT.search(title)
    if match and title.startswith(ISSUE_TITLE_PREFIX):
        return match.group(1)
    return None


def _issues_by_fingerprint(
    issues: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    """Index the bot's issues by fingerprint, preferring open, then newest."""
    index: dict[str, Mapping[str, Any]] = {}
    for issue in issues:
        if (issue.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        group = _issue_fingerprint(issue)
        if group is None:
            continue
        rank = (issue.get("state") == "open", issue.get("number", 0))
        current = index.get(group)
        if current is None or rank > (
            current.get("state") == "open",
            current["number"],
        ):
            index[group] = issue
    return index


def _meets_thresholds(occurrences: int, affected_requests: int) -> bool:
    return (
        occurrences >= MIN_PRODUCTION_OCCURRENCES
        and affected_requests >= MIN_PRODUCTION_REQUESTS
    )


def _folded(names: Iterable[str]) -> set[str]:
    """Return label names case-folded, as GitHub compares them."""
    return {name.casefold() for name in names}


def _issue_labels(group: ErrorGroup) -> list[str]:
    service_label = f"{SERVICE_LABEL_PREFIX}{group.family}"
    if len(service_label) > MAX_LABEL_LENGTH:
        return [BASE_LABEL]
    return [BASE_LABEL, service_label]


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class IssueSynchronizer:
    """Creates and updates one issue per production error group."""

    def __init__(
        self,
        github: GitHubClient,
        window: ReportingWindow,
        log_source: LogSource,
        *,
        dry_run: bool,
    ) -> None:
        """Sync the groups of ``window``; a dry run reads but never writes."""
        self._github = github
        self._window = window
        self._log_source = log_source
        self._dry_run = dry_run
        # Case-folded names: GitHub label names are unique regardless of case.
        self._known_labels: set[str] | None = None

    def run(self, groups: Iterable[ErrorGroup]) -> SyncResult:
        """Sync each group, opening at most five issues, largest groups first."""
        issues = _issues_by_fingerprint(self._github.list_issues(BOT_LOGIN))
        actions: list[SyncAction] = []
        opened = 0
        for group in groups:
            issue = issues.get(group.fingerprint)
            number: int | None = None
            if issue is not None:
                number = issue["number"]
                action = self._update(group, issue)
            elif not _meets_thresholds(
                group.production.occurrences, group.production.affected_requests
            ):
                action = "below-threshold"
            elif opened >= MAX_NEW_ISSUES_PER_RUN:
                action = "deferred"
            else:
                number = self._open(group)
                opened += 1
                action = "created"
            actions.append(
                SyncAction(
                    fingerprint=group.fingerprint,
                    kind=group.kind,
                    family=group.family,
                    production_occurrences=group.production.occurrences,
                    staging_occurrences=group.staging.occurrences,
                    issue_number=number,
                    action=action,
                )
            )
        deferred = sum(action.action == "deferred" for action in actions)
        return SyncResult(actions, deferred)

    def _ensure_labels(self, names: Iterable[str]) -> None:
        if self._known_labels is None:
            self._known_labels = _folded(self._github.list_labels())
        for name in names:
            if name.casefold() not in self._known_labels:
                color, description = LABEL_DETAILS.get(name, SERVICE_LABEL_DETAILS)
                self._github.create_label(name, color, description)
                self._known_labels.add(name.casefold())

    def _open(self, group: ErrorGroup) -> int | None:
        if self._dry_run:
            return None
        labels = _issue_labels(group)
        self._ensure_labels(labels)
        issue = self._github.create_issue(
            issue_title(group),
            issue_body(group, self._window, self._log_source),
            labels,
        )
        number = issue["number"]
        applied = _folded(label["name"] for label in issue.get("labels", []))
        missing = [label for label in labels if label.casefold() not in applied]
        if missing and not _folded(missing) <= _folded(
            self._github.add_labels(number, missing)
        ):
            msg = f"GitHub did not apply the labels to issue #{number}"
            raise GitHubLabelError(msg)
        return number

    def _reopen_since(self, issue: Mapping[str, Any]) -> datetime | None:
        """Return when regressions count from, if the issue should reopen."""
        if issue.get("state") != "closed":
            return None
        if issue.get("state_reason") not in REOPENABLE_CLOSE_REASONS:
            return None
        closed_at = _parse_time(issue.get("closed_at"))
        return None if closed_at is None else closed_at + REOPEN_DELAY

    def _update(self, group: ErrorGroup, issue: Mapping[str, Any]) -> str:
        body = issue.get("body") or ""
        state = parse_state(body)
        reported_end = _parse_time(state.get("window_end")) if state else None
        if reported_end is not None and reported_end > self._window.end:
            return "kept-newer"
        new_body = replace_section(
            body, issue_section(group, self._window, self._log_source)
        )
        since = self._reopen_since(issue)
        if since is not None and _meets_thresholds(*group.production_since(since)):
            if not self._dry_run:
                self._reopen(issue["number"], new_body, group, since)
            return "reopened"
        if new_body == body:
            return "unchanged"
        if not self._dry_run:
            self._github.update_issue(issue["number"], {"body": new_body})
        return "updated"

    def _reopen(
        self, number: int, body: str, group: ErrorGroup, since: datetime
    ) -> None:
        occurrences, affected_requests = group.production_since(since)
        self._ensure_labels([REGRESSION_LABEL])
        self._github.update_issue(
            number, {"body": body, "state": "open", "state_reason": "reopened"}
        )
        self._github.add_labels(number, [REGRESSION_LABEL])
        self._github.add_comment(
            number,
            "Production failures returned after this issue was closed: "
            f"{occurrences:,} occurrences in {affected_requests:,} requests since "
            f"{eastern_time(since)}, 24 hours after it was closed.",
        )


def sync_issues(
    groups: Iterable[ErrorGroup],
    window: ReportingWindow,
    log_source: LogSource,
    github: GitHubClient,
    *,
    dry_run: bool,
) -> SyncResult:
    """Create or update the issue for each group; a dry run makes no changes."""
    synchronizer = IssueSynchronizer(github, window, log_source, dry_run=dry_run)
    return synchronizer.run(groups)
