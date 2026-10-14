#!/usr/bin/env python3
"""Fetch and format changelog entries between two versions of a package.

Fetches CHANGELOG.md from the package's GitHub repo and extracts
entries between the old and new version, formatted as markdown.

Usage:
    python check_updates.py --package policyengine-us \
        --old-version 1.596.5 --new-version 1.604.1
"""

import argparse
import re
import sys
from http import HTTPStatus
from typing import TypedDict

import requests

# Map package names to GitHub repos
REPO_MAP = {
    "policyengine-us": "PolicyEngine/policyengine-us",
    "policyengine-uk": "PolicyEngine/policyengine-uk",
}


class ChangelogEntry(TypedDict):
    """One released version's changelog items, grouped by lowercase category."""

    version: str
    changes: dict[str, list[str]]


def fetch_changelog(package: str) -> str | None:
    """Fetch CHANGELOG.md from the package's GitHub repo."""
    repo = REPO_MAP.get(package)
    if not repo:
        return None
    for branch in ("main", "master"):
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/CHANGELOG.md"
        resp = requests.get(url, timeout=30)
        if resp.status_code == HTTPStatus.OK:
            return resp.text
    return None


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple."""
    return tuple(map(int, version_str.split(".")))


def parse_changelog(text: str | None) -> list[ChangelogEntry]:
    """Parse Keep-a-Changelog markdown into structured entries."""
    if not text:
        return []

    entries: list[ChangelogEntry] = []
    current_entry: ChangelogEntry | None = None
    current_category = None

    for line in text.splitlines():
        version_match = re.match(r"^##\s+\[(\d+\.\d+\.\d+)\]", line)
        if version_match:
            current_entry = {
                "version": version_match.group(1),
                "changes": {},
            }
            entries.append(current_entry)
            current_category = None
            continue

        if current_entry is None:
            continue

        category_match = re.match(r"^###\s+(\w+)", line)
        if category_match:
            current_category = category_match.group(1).lower()
            continue

        item_match = re.match(r"^-\s+(.+)", line)
        if item_match and current_category:
            current_entry["changes"].setdefault(current_category, [])
            current_entry["changes"][current_category].append(item_match.group(1))

    return entries


def get_changes_between(
    changelog: list[ChangelogEntry], old_version: str, new_version: str
) -> list[ChangelogEntry]:
    """Extract changelog entries between two versions."""
    old_v = parse_version(old_version)
    new_v = parse_version(new_version)
    return [
        e
        for e in changelog
        if "version" in e and old_v < parse_version(e["version"]) <= new_v
    ]


def format_changes(entries: list[ChangelogEntry]) -> str:
    """Format changelog entries as markdown sections."""
    buckets: dict[str, list[str]] = {
        "added": [],
        "changed": [],
        "fixed": [],
        "removed": [],
    }
    for entry in entries:
        for cat, items in entry.get("changes", {}).items():
            if cat in buckets:
                buckets[cat].extend(items)

    sections = []
    for cat, items in buckets.items():
        if items:
            sections.append(
                f"### {cat.capitalize()}\n" + "\n".join(f"- {item}" for item in items)
            )
    return "\n\n".join(sections) if sections else ""


def main() -> int:
    """Print the markdown changes between two versions of a package.

    Always return 0, so an unreachable changelog never fails the update job.
    """
    parser = argparse.ArgumentParser(
        description="Fetch changelog entries between two package versions."
    )
    parser.add_argument(
        "--package",
        required=True,
        help="Package name (e.g., policyengine-us)",
    )
    parser.add_argument("--old-version", required=True, help="Current pinned version")
    parser.add_argument("--new-version", required=True, help="New version from PyPI")
    args = parser.parse_args()

    changelog_text = fetch_changelog(args.package)
    if not changelog_text:
        print(f"Could not fetch changelog for {args.package}.", file=sys.stderr)
        return 0

    entries = parse_changelog(changelog_text)
    changes = get_changes_between(entries, args.old_version, args.new_version)

    if changes:
        print(format_changes(changes))
    else:
        print("No changelog entries found between these versions.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
