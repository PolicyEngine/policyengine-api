"""Characterization tests for fetching a package's changelog from GitHub."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

CHECK_UPDATES_PATH = (
    Path(__file__).parents[2] / ".github" / "scripts" / "check_updates.py"
)


def _load_check_updates():
    spec = importlib.util.spec_from_file_location("check_updates", CHECK_UPDATES_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("status_by_branch", "expected_text", "expected_branches"),
    [
        ({"main": 200, "master": 200}, "changelog from main", ["main"]),
        ({"main": 404, "master": 200}, "changelog from master", ["main", "master"]),
        ({"main": 404, "master": 500}, None, ["main", "master"]),
        ({"main": 201, "master": 204}, None, ["main", "master"]),
    ],
)
def test_fetch_changelog_uses_the_first_branch_that_answers_ok(
    monkeypatch, status_by_branch, expected_text, expected_branches
):
    check_updates = _load_check_updates()
    requested = []

    def fake_get(url, timeout):
        branch = url.split("/")[-2]
        requested.append((url, timeout))
        return SimpleNamespace(
            status_code=status_by_branch[branch], text=f"changelog from {branch}"
        )

    monkeypatch.setattr(check_updates.requests, "get", fake_get)

    assert check_updates.fetch_changelog("policyengine-us") == expected_text
    assert requested == [
        (
            "https://raw.githubusercontent.com/PolicyEngine/policyengine-us/"
            f"{branch}/CHANGELOG.md",
            30,
        )
        for branch in expected_branches
    ]


def test_fetch_changelog_skips_unknown_packages(monkeypatch):
    check_updates = _load_check_updates()
    monkeypatch.setattr(
        check_updates.requests,
        "get",
        lambda *_args, **_kwargs: pytest.fail("no request expected"),
    )

    assert check_updates.fetch_changelog("policyengine-ca") is None
