"""Command line: ``python -m scripts.rules {validate,render,guard}``."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from scripts.rules import ci_scripts
from scripts.rules.guard import REPO_ROOT, run_guard
from scripts.rules.load import load_registry
from scripts.rules.render import write_outputs
from scripts.rules.resolve import clear_caches
from scripts.rules.validate import validate


def _report(message: str) -> None:
    """Print one line of the command's output."""
    print(message)


def _print(violations: list, notes: list[str] | None = None) -> int:
    for note in notes or []:
        _report(f"note: {note}")
    for violation in violations:
        _report(f"  - {violation}")
    _report("rules: failed" if violations else "rules: passed")
    return 1 if violations else 0


def _ci_scripts_command(root: Path, *, write_baselines: bool) -> int:
    """Check the workflow scripts, or record today's findings as the baselines."""
    if not write_baselines:
        violations, notes = ci_scripts.run_check(root)
        return _print(violations, notes)
    registry, violations = load_registry(root)
    if registry is None or registry.ci_scripts is None:
        return _print(violations or ["no [ci_scripts] table"])
    ci_scripts.write_baselines(
        registry, ci_scripts.find(registry.ci_scripts, root), root
    )
    _report("wrote ci_scripts baselines; update the rules' baseline counts")
    return 0


def _registry_command(command: str, root: Path) -> int:
    """Validate the registry and, for ``render``, write its views once it is valid."""
    clear_caches()
    registry, violations = load_registry(root)
    if registry is None:
        return _print(violations)
    violations += validate(registry, root, date.today())
    if command != "render":
        return _print(violations)
    if violations:
        _report("render refused: fix the registry first")
        return _print(violations)
    for path in write_outputs(registry, root):
        _report(f"wrote {path.relative_to(root)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run one rules command and return 1 if it found violations.

    ``render`` refuses to write anything while the registry fails validation.
    """
    parser = argparse.ArgumentParser(
        prog="python -m scripts.rules", description=__doc__
    )
    parser.add_argument(
        "command", choices=["validate", "render", "guard", "ci-scripts"]
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    parser.add_argument(
        "--base-ref",
        help="git ref to compare baselines against (default: origin/$GITHUB_BASE_REF)",
    )
    parser.add_argument(
        "--write-baselines",
        action="store_true",
        help=(
            "ci-scripts only: record today's findings as the baselines "
            "(when adopting the rule)"
        ),
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.command == "ci-scripts":
        return _ci_scripts_command(root, write_baselines=args.write_baselines)
    if args.command == "guard":
        result = run_guard(root, base_ref=args.base_ref)
        return _print(result.violations, result.notes)
    return _registry_command(args.command, root)
