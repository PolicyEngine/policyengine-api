"""Tests for telemetry_error_issues.github_client: paging, write spacing, retries."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from telemetry_error_issues.github_client import GitHubError
from telemetry_error_issues.transport import HttpResponse

from tests.unit.telemetry_error_issues.github_support import (
    BOT,
    FakeGitHub,
    bot_issue,
    failures,
    groups_for_report_date,
    sync,
)


def test_sync_lists_open_and_closed_issues_from_the_bot_page_by_page() -> None:
    github = FakeGitHub([bot_issue(number) for number in range(1, 151)])

    sync([], github)

    listing = [
        parse_qs(urlsplit(request.url).query)
        for _, request in github.requests
        if urlsplit(request.url).path.endswith("/issues")
    ]
    assert len(listing) == 2
    assert listing[0]["creator"] == [BOT]
    assert listing[0]["state"] == ["all"]
    assert listing[0]["per_page"] == ["100"]
    assert [query["page"] for query in listing] == [["1"], ["2"]]


def test_sync_writes_one_at_a_time_at_least_a_second_apart() -> None:
    records = []
    for index in range(3):
        records += failures(
            3, request_key_prefix=f"g{index}-", error_type=f"Error{index}"
        )
    github = FakeGitHub()

    sync(groups_for_report_date(records), github)

    write_times = [moment for moment, _ in github.writes]
    assert len(write_times) == 5
    assert all(
        later - earlier >= 1.0 for earlier, later in itertools.pairwise(write_times)
    )


@pytest.mark.parametrize("status", [403, 429])
def test_sync_waits_for_retry_after_on_rate_limits(status: int) -> None:
    groups = groups_for_report_date(failures(3))
    github = FakeGitHub(labels=("telemetry-error", "service: policyengine-api"))
    github.failures = [
        HttpResponse(
            status=status, reason="Forbidden", headers={"retry-after": "7"}, body=b"{}"
        )
    ]

    sync(groups, github)

    assert 7 in github.sleeps
    assert len(github.issues) == 1


def _limited_github(response: object) -> FakeGitHub:
    """Return a fake whose first write gets ``response`` and later writes succeed."""
    github = FakeGitHub(labels=("telemetry-error", "service: policyengine-api"))
    github.failures = [response]
    return github


def test_sync_waits_a_minute_on_a_secondary_rate_limit_without_retry_after() -> None:
    body = b'{"message": "You have exceeded a secondary rate limit. Please wait."}'
    github = _limited_github(
        HttpResponse(status=403, reason="Forbidden", headers={}, body=body),
    )

    sync(groups_for_report_date(failures(3)), github)

    assert 60 in github.sleeps
    assert len(github.issues) == 1


def test_sync_waits_until_an_exhausted_rate_limit_resets() -> None:
    headers = {
        "date": "Tue, 20 Oct 2026 23:00:00 GMT",
        "x-ratelimit-remaining": "0",
        "x-ratelimit-reset": str(
            int(datetime(2026, 10, 20, 23, 0, 42, tzinfo=UTC).timestamp())
        ),
    }
    github = _limited_github(
        HttpResponse(status=403, reason="Forbidden", headers=headers, body=b"{}"),
    )

    sync(groups_for_report_date(failures(3)), github)

    assert 42 in github.sleeps
    assert len(github.issues) == 1


def test_sync_fails_instead_of_waiting_hours_for_a_rate_limit_reset() -> None:
    headers = {
        "date": "Tue, 20 Oct 2026 23:00:00 GMT",
        "x-ratelimit-remaining": "0",
        "x-ratelimit-reset": str(
            int(datetime(2026, 10, 21, 0, 0, tzinfo=UTC).timestamp())
        ),
    }
    github = _limited_github(
        HttpResponse(status=403, reason="Forbidden", headers=headers, body=b"{}"),
    )

    with pytest.raises(GitHubError, match="HTTP 403"):
        sync(groups_for_report_date(failures(3)), github)

    assert github.sleeps == []


def test_sync_stops_after_three_rate_limit_retries() -> None:
    groups = groups_for_report_date(failures(3))
    github = FakeGitHub(labels=("telemetry-error", "service: policyengine-api"))
    limited = HttpResponse(
        status=429, reason="Too Many Requests", headers={"retry-after": "2"}, body=b"{}"
    )
    github.failures = [limited] * 4

    with pytest.raises(GitHubError) as raised:
        sync(groups, github)

    assert str(raised.value) == "GitHub request failed: HTTP 429 Too Many Requests"
    assert github.sleeps.count(2) == 3


def test_sync_reports_a_forbidden_write_without_retrying() -> None:
    groups = groups_for_report_date(failures(3))
    github = FakeGitHub(labels=("telemetry-error", "service: policyengine-api"))
    github.failures = [
        HttpResponse(
            status=403,
            reason="Forbidden",
            headers={},
            body=b'{"message": "SENTINEL Resource not accessible"}',
        )
    ]

    with pytest.raises(GitHubError) as raised:
        sync(groups, github)

    assert str(raised.value) == "GitHub request failed: HTTP 403 Forbidden"
    assert len(github.writes) == 1
