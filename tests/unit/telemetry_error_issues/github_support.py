"""An in-memory GitHub issues API, and helpers that sync issues against it."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from telemetry_error_issues.github_client import GitHubClient
from telemetry_error_issues.groups import build_groups
from telemetry_error_issues.sync import sync_issues
from telemetry_error_issues.transport import HttpResponse
from telemetry_error_issues.window import reporting_window

from tests.unit.telemetry_error_issues.report_support import (
    FINGERPRINT_KEY,
    PROJECT_ID,
    REPORT_DATE,
    exception_record,
    hours_after_window_noon,
)

REPOSITORY = "PolicyEngine/policyengine-api"
BOT = "github-actions[bot]"


class FakeGitHub:
    """An in-memory GitHub issues API with a clock that advances when it sleeps."""

    def __init__(
        self,
        issues: list[dict] = (),
        labels: tuple[str, ...] = (),
        *,
        drop_created_labels: bool = False,
    ) -> None:
        self.issues = {issue["number"]: dict(issue) for issue in issues}
        self.labels = set(labels)
        self.drop_created_labels = drop_created_labels
        self.failures: list[object] = []
        self.requests: list[tuple[float, object]] = []
        self.comments: dict[int, list[str]] = {}
        self.sleeps: list[float] = []
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now

    def client(self) -> object:
        return GitHubClient(
            REPOSITORY, "fake-github-token", self, sleep=self.sleep, clock=self.clock
        )

    @property
    def writes(self) -> list[tuple[float, object]]:
        return [entry for entry in self.requests if entry[1].method != "GET"]

    def _respond(self, payload: object, status: int = 200) -> object:
        return HttpResponse(
            status=status, reason="OK", headers={}, body=json.dumps(payload).encode()
        )

    def __call__(self, request: object) -> object:
        self.requests.append((self.now, request))
        if request.method != "GET" and self.failures:
            return self.failures.pop(0)
        split = urlsplit(request.url)
        path = split.path.removeprefix(f"/repos/{REPOSITORY}")
        query = {name: values[0] for name, values in parse_qs(split.query).items()}
        body = json.loads(request.body) if request.body else None
        return self._route(request.method, path, query, body)

    def _route(self, method: str, path: str, query: dict, body: dict | None) -> object:
        parts = path.strip("/").split("/")
        if len(parts) > 1:
            return self._route_issue(method, int(parts[1]), parts[2:], body)
        if method == "GET" and parts == ["issues"]:
            issues = sorted(self.issues.values(), key=lambda issue: issue["number"])
            return self._respond(self._page(issues, query))
        if method == "GET":
            labels = [{"name": name} for name in sorted(self.labels)]
            return self._respond(self._page(labels, query))
        if parts == ["labels"]:
            # GitHub label names are unique regardless of case.
            if body["name"].casefold() in {name.casefold() for name in self.labels}:
                return self._respond({"message": "Validation Failed"}, status=422)
            self.labels.add(body["name"])
            return self._respond({"name": body["name"]}, status=201)
        return self._create(body)

    def _existing_label_names(self, requested: list[str]) -> list[str]:
        """Return the stored spelling of each label, as GitHub applies them."""
        stored = {name.casefold(): name for name in self.labels}
        return [stored.get(name.casefold(), name) for name in requested]

    def _route_issue(
        self, method: str, number: int, rest: list[str], body: dict
    ) -> object:
        if method == "PATCH":
            self.issues[number].update(body)
            return self._respond(self.issues[number])
        if rest == ["labels"]:
            names = {label["name"] for label in self.issues[number]["labels"]}
            if not self.drop_created_labels:
                names |= set(self._existing_label_names(body["labels"]))
            self.issues[number]["labels"] = [{"name": name} for name in sorted(names)]
            return self._respond(self.issues[number]["labels"])
        self.comments.setdefault(number, []).append(body["body"])
        return self._respond({"id": 1}, status=201)

    def _page(self, items: list, query: dict) -> list:
        page = int(query.get("page", "1"))
        size = int(query.get("per_page", "30"))
        return items[(page - 1) * size : page * size]

    def _create(self, body: dict) -> object:
        number = max(self.issues, default=0) + 1
        labels = (
            []
            if self.drop_created_labels
            else self._existing_label_names(body["labels"])
        )
        self.issues[number] = {
            "number": number,
            "title": body["title"],
            "body": body["body"],
            "state": "open",
            "state_reason": None,
            "closed_at": None,
            "labels": [{"name": name} for name in labels],
            "user": {"login": BOT},
        }
        return self._respond(self.issues[number], status=201)


def bot_issue(number: int, **fields: object) -> dict:
    issue = {
        "number": number,
        "title": f"Issue {number}",
        "body": "",
        "state": "open",
        "state_reason": None,
        "closed_at": None,
        "labels": [],
        "user": {"login": BOT},
    }
    issue.update(fields)
    return issue


def failures(
    count: int,
    *,
    request_key_prefix: str = "r",
    **fields: object,
) -> list:
    return [
        exception_record(
            request_key=f"{request_key_prefix}{index}",
            timestamp=hours_after_window_noon(index),
            **fields,
        )
        for index in range(count)
    ]


def groups_for_report_date(records: list) -> list:
    return build_groups(records, [], reporting_window(REPORT_DATE), FINGERPRINT_KEY)


def sync(groups: list, github: FakeGitHub, *, dry_run=False):
    return sync_issues(
        groups,
        reporting_window(REPORT_DATE),
        PROJECT_ID,
        github.client(),
        dry_run=dry_run,
    )
