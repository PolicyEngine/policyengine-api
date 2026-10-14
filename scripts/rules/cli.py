"""Command line: ``python -m scripts.rules {validate,render,guard}``."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from scripts.rules.guard import REPO_ROOT, run_guard
from scripts.rules.load import load_registry
from scripts.rules.render import write_outputs
from scripts.rules.resolve import clear_caches
from scripts.rules.validate import validate


def _print(violations: list, notes: list[str] | None = None) -> int:
    for note in notes or []:
        print(f"note: {note}")
    for violation in violations:
        print(f"  - {violation}")
    print("rules: failed" if violations else "rules: passed")
    return 1 if violations else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.rules", description=__doc__
    )
    parser.add_argument("command", choices=["validate", "render", "guard"])
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    parser.add_argument(
        "--base-ref",
        help="git ref to compare baselines against (default: origin/$GITHUB_BASE_REF)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.command == "guard":
        result = run_guard(root, base_ref=args.base_ref)
        return _print(result.violations, result.notes)

    clear_caches()
    registry, violations = load_registry(root)
    if registry is None:
        return _print(violations)
    violations += validate(registry, root, date.today())
    if args.command == "render":
        if violations:
            print("render refused: fix the registry first")
            return _print(violations)
        for path in write_outputs(registry, root):
            print(f"wrote {path.relative_to(root)}")
        return 0
    return _print(violations)
