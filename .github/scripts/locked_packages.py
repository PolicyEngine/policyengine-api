"""Read package names and versions from uv.lock for the daily relock.

The relock upgrades every locked package except the PolicyEngine .py bundle
(``policyengine``) and the packages that the bundle's extras pin: PolicyEngine
Core, the country models and the SPM calculator. Those change only through the
bundle update workflow (update-policyengine-bundle.yaml), whose pull requests
run the check that the simulation API supports the bundle. The project itself
is never upgraded.

Usage:
    locked_packages.py upgradeable LOCK  names it may upgrade, one per line
    locked_packages.py held LOCK         "name version" of each package it holds
    locked_packages.py summary OLD NEW   Markdown summary of the changes
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

BUNDLE_PACKAGE = "policyengine"
PROJECT_SOURCES = ("editable", "virtual")


def _locked_versions(lock_path: Path) -> tuple[dict[str, list[str]], set[str]]:
    """Return each locked package's versions, and the names the relock holds.

    A package can be locked at more than one version, one per set of Python
    or platform markers, so each name maps to a sorted list of versions. The
    project's own entry is left out.

    Raises:
        SystemExit: when the bundle package is not in the lock, since the held
            packages can't be identified without it.

    """
    with lock_path.open("rb") as lock_file:
        packages = tomllib.load(lock_file).get("package", [])

    versions: dict[str, set[str]] = {}
    held = {BUNDLE_PACKAGE}
    bundle_locked = False
    for package in packages:
        source = package.get("source", {})
        if any(kind in source for kind in PROJECT_SOURCES):
            continue
        name = package["name"]
        versions.setdefault(name, set()).add(package["version"])
        if name == BUNDLE_PACKAGE:
            bundle_locked = True
            for members in package.get("optional-dependencies", {}).values():
                held.update(member["name"] for member in members)

    if not bundle_locked:
        message = (
            f"{BUNDLE_PACKAGE} is not locked in {lock_path}, so the packages "
            "its extras pin can't be held back."
        )
        raise SystemExit(message)
    return {name: sorted(found) for name, found in versions.items()}, held


def upgradeable(lock_path: Path) -> list[str]:
    """Return the sorted names of the locked packages the relock may upgrade."""
    versions, held = _locked_versions(lock_path)
    return sorted(name for name in versions if name not in held)


def held_versions(lock_path: Path) -> list[str]:
    """Return "name version" for each locked package the relock must not move."""
    versions, held = _locked_versions(lock_path)
    return [
        f"{name} {', '.join(versions[name])}"
        for name in sorted(held)
        if name in versions
    ]


def summary(old_lock: Path, new_lock: Path) -> str:
    """Return a Markdown summary of the version changes from old_lock to new_lock."""
    old_versions, _ = _locked_versions(old_lock)
    new_versions, held = _locked_versions(new_lock)

    changes = []
    for name in sorted(old_versions.keys() | new_versions.keys()):
        old = ", ".join(old_versions.get(name, []))
        new = ", ".join(new_versions.get(name, []))
        if not old:
            changes.append(f"- `{name}`: newly locked at {new}")
        elif not new:
            changes.append(f"- `{name}`: no longer locked (was {old})")
        elif old != new:
            changes.append(f"- `{name}`: {old} → {new}")
    if not changes:
        changes.append(
            "- No package versions changed; only the files or metadata recorded "
            "for the locked versions did."
        )

    held_lines = [
        f"- `{name}` {', '.join(new_versions[name])}"
        for name in sorted(held)
        if name in new_versions
    ]
    return "\n".join(
        [
            "## Version changes",
            "",
            *changes,
            "",
            "## Held for the bundle update workflow",
            "",
            "These packages change only through the PolicyEngine bundle update "
            "workflow (`update-policyengine-bundle.yaml`), whose pull requests "
            "check that the simulation API supports the bundle:",
            "",
            *held_lines,
            "",
        ]
    )


def main() -> None:
    """Print the result of the requested command."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("upgradeable").add_argument("lock", type=Path)
    commands.add_parser("held").add_argument("lock", type=Path)
    summary_parser = commands.add_parser("summary")
    summary_parser.add_argument("old_lock", type=Path)
    summary_parser.add_argument("new_lock", type=Path)
    arguments = parser.parse_args()

    if arguments.command == "upgradeable":
        print("\n".join(upgradeable(arguments.lock)))
    elif arguments.command == "held":
        print("\n".join(held_versions(arguments.lock)))
    else:
        sys.stdout.write(summary(arguments.old_lock, arguments.new_lock))


if __name__ == "__main__":
    main()
