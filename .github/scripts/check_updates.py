#!/usr/bin/env python3
"""
Check for PolicyEngine country package updates and generate PR summary.

Checks PyPI for newer versions of country packages pinned in
pyproject.toml. If updates are found, edits pyproject.toml, creates a
changelog fragment, and writes a PR summary file.
"""

import os
import re
import sys

import requests

# Packages to track — must match the exact names used in pyproject.toml
PACKAGES = ["policyengine_us", "policyengine_uk"]

# Map package names to GitHub repos (for fetching changelogs)
REPO_MAP = {
    "policyengine_us": "PolicyEngine/policyengine-us",
    "policyengine_uk": "PolicyEngine/policyengine-uk",
}


def get_current_versions(pyproject_content):
    """Extract current pinned versions from pyproject.toml."""
    versions = {}
    for pkg in PACKAGES:
        pattern = rf"{pkg.replace('_', '[-_]')}==([0-9]+\.[0-9]+\.[0-9]+)"
        match = re.search(pattern, pyproject_content)
        if match:
            versions[pkg] = match.group(1)
    return versions


def get_latest_versions():
    """Fetch latest versions from PyPI."""
    versions = {}
    for pkg in PACKAGES:
        pypi_name = pkg.replace("_", "-")
        resp = requests.get(f"https://pypi.org/pypi/{pypi_name}/json")
        if resp.status_code == 200:
            versions[pkg] = resp.json()["info"]["version"]
    return versions


def find_updates(current, latest):
    """Return dict of packages that have newer versions on PyPI."""
    updates = {}
    for pkg in PACKAGES:
        if pkg in current and pkg in latest and current[pkg] != latest[pkg]:
            updates[pkg] = {"old": current[pkg], "new": latest[pkg]}
    return updates


def update_pyproject(content, updates):
    """Replace pinned versions in pyproject.toml content."""
    for pkg, versions in updates.items():
        pattern = rf"({pkg.replace('_', '[-_]')}==)[0-9]+\.[0-9]+\.[0-9]+"
        content = re.sub(pattern, rf"\g<1>{versions['new']}", content)
    return content


def fetch_changelog(pkg):
    """Fetch CHANGELOG.md from the package's GitHub repo."""
    repo = REPO_MAP.get(pkg)
    if not repo:
        return None
    # Try main first, then master
    for branch in ("main", "master"):
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/CHANGELOG.md"
        resp = requests.get(url)
        if resp.status_code == 200:
            return resp.text
    return None


def parse_version(version_str):
    """Parse a version string into a comparable tuple."""
    return tuple(map(int, version_str.split(".")))


def parse_changelog(text):
    """Parse Keep-a-Changelog markdown into structured entries."""
    if not text:
        return []

    entries = []
    current_entry = None
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


def get_changes_between(changelog, old_version, new_version):
    """Extract changelog entries between two versions."""
    old_v = parse_version(old_version)
    new_v = parse_version(new_version)
    return [
        e
        for e in changelog
        if "version" in e and old_v < parse_version(e["version"]) <= new_v
    ]


def format_changes(entries):
    """Format changelog entries as markdown sections."""
    buckets = {"added": [], "changed": [], "fixed": [], "removed": []}
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
    return "\n\n".join(sections) if sections else "No detailed changes available."


def generate_summary(updates):
    """Build a PR summary with version table and changelogs."""
    parts = []

    table = "| Package | Old Version | New Version |\n|---------|-------------|-------------|\n"
    for pkg, v in updates.items():
        table += f"| {pkg} | {v['old']} | {v['new']} |\n"
    parts.append(table)

    for pkg, v in updates.items():
        changelog_text = fetch_changelog(pkg)
        changelog = parse_changelog(changelog_text) if changelog_text else None
        if changelog:
            entries = get_changes_between(changelog, v["old"], v["new"])
            if entries:
                formatted = format_changes(entries)
                parts.append(
                    f"## What Changed ({pkg} {v['old']} → {v['new']})\n\n{formatted}"
                )
            else:
                parts.append(
                    f"## What Changed ({pkg} {v['old']} → {v['new']})\n\n"
                    "No changelog entries found between these versions."
                )

    return "\n\n".join(parts)


def write_github_output(key, value):
    """Write a key=value pair to the GitHub Actions output file."""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


def main():
    with open("pyproject.toml", "r") as f:
        content = f.read()

    current = get_current_versions(content)
    print(f"Current versions: {current}")

    latest = get_latest_versions()
    print(f"Latest versions:  {latest}")

    updates = find_updates(current, latest)
    if not updates:
        print("No updates available.")
        write_github_output("has_updates", "false")
        return 0

    print(f"Updates available: {updates}")

    # Update pyproject.toml
    new_content = update_pyproject(content, updates)
    with open("pyproject.toml", "w") as f:
        f.write(new_content)

    # Generate PR summary
    summary = generate_summary(updates)
    with open("pr_summary.md", "w") as f:
        f.write(summary)

    # Create changelog fragment(s) in changelog.d/
    for pkg, v in updates.items():
        pretty = pkg.replace("_", " ").replace("policyengine", "PolicyEngine")
        fragment = f"changelog.d/update-{pkg.replace('_', '-')}-{v['new']}.changed.md"
        with open(fragment, "w") as f:
            f.write(f"Update {pretty} to {v['new']}.\n")

    # Set outputs
    write_github_output("has_updates", "true")
    updates_str = ", ".join(f"{pkg} to {v['new']}" for pkg, v in updates.items())
    write_github_output("updates_summary", updates_str)

    print("Updates prepared successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
