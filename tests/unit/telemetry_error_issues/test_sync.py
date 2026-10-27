"""Tests for telemetry_error_issues.sync: opening, updating and reopening issues."""

from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from telemetry_error_issues.github_client import GitHubError
from telemetry_error_issues.rendering import (
    SECTION_END,
    issue_body,
    issue_section,
    issue_title,
)
from telemetry_error_issues.window import reporting_window

from tests.unit.telemetry_error_issues.github_support import (
    FakeGitHub,
    bot_issue,
    failures,
    groups_for_report_date,
    sync,
)
from tests.unit.telemetry_error_issues.report_support import (
    LOG_SOURCE,
    REPORT_DATE,
    WINDOW_NOON,
    exception_record,
    hours_after_window_noon,
)


def _existing_issue(group: object, number: int = 7, **fields: object) -> dict:
    """Return the issue the job opened for ``group`` on an earlier day."""
    earlier = reporting_window(REPORT_DATE - timedelta(days=1))
    issue = bot_issue(
        number,
        title=issue_title(group),
        body=issue_body(group, earlier, LOG_SOURCE),
    )
    issue.update(fields)
    return issue


def test_sync_opens_an_issue_at_three_production_occurrences_in_two_requests() -> None:
    eligible = failures(3)
    # Three failures that all affected the request with observability ID o1.
    one_request = [
        exception_record(
            error_type="KeyError",
            request_key=None,
            trace_key=None,
            observability_key="o1",
            timestamp=hours_after_window_noon(index),
        )
        for index in range(3)
    ]
    too_few = failures(2, request_key_prefix="few", error_type="TypeError")
    groups = groups_for_report_date(eligible + one_request + too_few)
    github = FakeGitHub()

    result = sync(groups, github)

    created = list(github.issues.values())
    eligible_group = next(
        group for group in groups if group.error_type == "StaleDataError"
    )
    assert [issue["title"] for issue in created] == [issue_title(eligible_group)]
    assert created[0]["labels"] == [
        {"name": "telemetry-error"},
        {"name": "service: policyengine-api"},
    ]
    actions = {action.fingerprint: action.action for action in result.actions}
    assert sorted(actions.values()) == ["below-threshold", "below-threshold", "created"]


def test_sync_never_opens_an_issue_for_a_staging_only_group() -> None:
    groups = groups_for_report_date(failures(10, environment_name="staging"))
    github = FakeGitHub()

    result = sync(groups, github)

    assert github.issues == {}
    assert result.actions[0].action == "below-threshold"


def test_sync_opens_at_most_five_issues_in_order_of_production_volume() -> None:
    records = []
    for index in range(7):
        records += failures(
            3 + index,
            request_key_prefix=f"g{index}-",
            error_type=f"Error{index}",
        )
    groups = groups_for_report_date(records)
    github = FakeGitHub()

    result = sync(groups, github)

    titles = [issue["title"] for issue in github.issues.values()]
    assert [title.split(": ")[1].split(" ")[0] for title in titles] == [
        "Error6",
        "Error5",
        "Error4",
        "Error3",
        "Error2",
    ]
    assert result.deferred == 2
    assert [action.action for action in result.actions].count("deferred") == 2


def test_sync_replaces_only_the_marked_section_and_never_the_title() -> None:
    group = groups_for_report_date(failures(3))[0]
    issue = _existing_issue(group, title="Renamed by a person")
    issue["body"] = f"Notes before.\n\n{issue['body']}\nNotes after.\n"
    github = FakeGitHub([issue])

    result = sync([group], github)

    patch = json.loads(github.writes[0][1].body)
    expected_section = issue_section(group, reporting_window(REPORT_DATE), LOG_SOURCE)
    assert list(patch) == ["body"]
    assert patch["body"].startswith("Notes before.\n\n")
    assert patch["body"].endswith("\nNotes after.\n")
    assert expected_section in patch["body"]
    assert github.issues[7]["title"] == "Renamed by a person"
    assert result.actions[0].action == "updated"
    assert result.actions[0].issue_number == 7


def test_sync_does_not_write_when_the_section_is_unchanged() -> None:
    group = groups_for_report_date(failures(3))[0]
    github = FakeGitHub([_existing_issue(group)])

    sync([group], github)
    first_run_writes = len(github.writes)
    second = sync([group], github)

    assert first_run_writes == 1
    assert len(github.writes) == 1
    assert second.actions[0].action == "unchanged"


def test_sync_adds_a_deleted_section_back_at_the_end() -> None:
    group = groups_for_report_date(failures(3))[0]
    issue = _existing_issue(group, body="Only human notes now.")
    github = FakeGitHub([issue])

    sync([group], github)

    body = github.issues[7]["body"]
    assert body.startswith("Only human notes now.\n\n")
    assert body.rstrip().endswith(SECTION_END)
    assert len(github.issues) == 1


def test_sync_ignores_issues_opened_by_other_authors() -> None:
    group = groups_for_report_date(failures(3))[0]
    person_issue = _existing_issue(group, user={"login": "someone"})
    github = FakeGitHub([person_issue])

    sync([group], github)

    assert github.issues[7]["body"] == person_issue["body"]
    assert len(github.issues) == 2


def test_sync_reopens_a_completed_issue_when_production_failures_return() -> None:
    group = groups_for_report_date(failures(4))[0]
    closed_at = (WINDOW_NOON - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    issue = _existing_issue(
        group,
        state="closed",
        state_reason="completed",
        closed_at=closed_at,
    )
    github = FakeGitHub([issue], labels=("telemetry-error",))

    result = sync([group], github)

    reopened = github.issues[7]
    assert reopened["state"] == "open"
    assert reopened["state_reason"] == "reopened"
    assert {"name": "regression"} in reopened["labels"]
    assert "regression" in github.labels
    assert github.comments[7] == [
        "Production failures returned after this issue was closed: 4 occurrences "
        "in 4 requests since 2026-10-19 12:00 EDT, 24 hours after it was closed."
    ]
    assert result.actions[0].action == "reopened"


def test_sync_treats_an_issue_closed_without_a_reason_as_completed() -> None:
    group = groups_for_report_date(failures(3))[0]
    closed_at = (WINDOW_NOON - timedelta(days=2)).isoformat()
    issue = _existing_issue(
        group, state="closed", state_reason=None, closed_at=closed_at
    )
    github = FakeGitHub([issue])

    result = sync([group], github)

    assert github.issues[7]["state"] == "open"
    assert result.actions[0].action == "reopened"


def test_sync_keeps_a_completed_issue_closed_within_24_hours_of_closing() -> None:
    group = groups_for_report_date(failures(4))[0]
    closed_at = (WINDOW_NOON - timedelta(hours=12)).isoformat()
    issue = _existing_issue(
        group,
        state="closed",
        state_reason="completed",
        closed_at=closed_at,
    )
    github = FakeGitHub([issue])

    result = sync([group], github)

    assert github.issues[7]["state"] == "closed"
    assert 7 not in github.comments
    assert (
        issue_section(group, reporting_window(REPORT_DATE), LOG_SOURCE)
        in github.issues[7]["body"]
    )
    assert result.actions[0].action == "updated"


@pytest.mark.parametrize("reason", ["not_planned", "duplicate"])
def test_sync_updates_but_never_reopens_not_planned_or_duplicate_issues(
    reason: str,
) -> None:
    group = groups_for_report_date(failures(10))[0]
    closed_at = (WINDOW_NOON - timedelta(days=5)).isoformat()
    issue = _existing_issue(
        group, state="closed", state_reason=reason, closed_at=closed_at
    )
    github = FakeGitHub([issue])

    result = sync([group], github)

    assert github.issues[7]["state"] == "closed"
    assert result.actions[0].action == "updated"
    assert len(github.issues) == 1


def test_sync_keeps_a_newer_report_instead_of_overwriting_it() -> None:
    group = groups_for_report_date(failures(3))[0]
    later = reporting_window(REPORT_DATE + timedelta(days=1))
    issue = bot_issue(
        7,
        title=issue_title(group),
        body=issue_body(group, later, LOG_SOURCE),
    )
    github = FakeGitHub([issue])

    result = sync([group], github)

    assert github.writes == []
    assert result.actions[0].action == "kept-newer"


def test_sync_creates_missing_labels_before_opening_issues() -> None:
    groups = groups_for_report_date(failures(3))
    github = FakeGitHub(labels=("telemetry-error",))

    sync(groups, github)

    created_labels = [
        json.loads(request.body)["name"]
        for _, request in github.writes
        if urlsplit(request.url).path.endswith("/labels")
    ]
    assert created_labels == ["service: policyengine-api"]


def test_sync_uses_existing_labels_whatever_their_case() -> None:
    groups = groups_for_report_date(failures(3))
    github = FakeGitHub(labels=("Telemetry-Error", "Service: Policyengine-Api"))

    sync(groups, github)

    created_labels = [
        request
        for _, request in github.writes
        if urlsplit(request.url).path.endswith("/labels")
    ]
    assert created_labels == []
    assert github.issues[1]["labels"] == [
        {"name": "Telemetry-Error"},
        {"name": "Service: Policyengine-Api"},
    ]


def test_sync_reopens_with_an_existing_regression_label_of_another_case() -> None:
    group = groups_for_report_date(failures(4))[0]
    closed_at = (WINDOW_NOON - timedelta(days=2)).isoformat()
    issue = _existing_issue(
        group,
        state="closed",
        state_reason="completed",
        closed_at=closed_at,
    )
    github = FakeGitHub([issue], labels=("Regression",))

    result = sync([group], github)

    assert result.actions[0].action == "reopened"
    assert {"name": "Regression"} in github.issues[7]["labels"]
    assert github.labels == {"Regression"}


def test_sync_adds_labels_a_create_response_is_missing() -> None:
    groups = groups_for_report_date(failures(3))
    github = FakeGitHub(drop_created_labels=True)

    with pytest.raises(GitHubError, match="labels"):
        sync(groups, github)

    added = [
        request
        for _, request in github.writes
        if urlsplit(request.url).path.endswith("/issues/1/labels")
    ]
    assert len(added) == 1


def test_sync_dry_run_makes_no_write_calls() -> None:
    eligible = groups_for_report_date(failures(3))[0]
    existing = groups_for_report_date(failures(3, error_type="KeyError"))[0]
    github = FakeGitHub([_existing_issue(existing)])

    result = sync([eligible, existing], github, dry_run=True)

    assert github.writes == []
    assert sorted(action.action for action in result.actions) == ["created", "updated"]
