"""The registry guard: every check in one pass."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from scripts.rules.adapters import check_adapters
from scripts.rules.baseline import (
    BaseUnavailable,
    check_baselines,
    default_base_ref,
    load_base_registry,
)
from scripts.rules.discover import discover_hidden
from scripts.rules.load import load_registry
from scripts.rules.model import Registry, Violation
from scripts.rules.render import (
    AGENTS_MD,
    RULES_MD,
    extract_block,
    render_agents_block,
    render_rules_md,
)
from scripts.rules.resolve import (
    clear_caches,
    resolve_ci,
    resolve_enforcer,
    resolve_proof_ci,
)
from scripts.rules.validate import validate

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_FIX = "run python -m scripts.rules render and commit the result"


@dataclass
class GuardResult:
    violations: list[Violation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _stale_outputs(registry: Registry, root: Path) -> list[Violation]:
    violations = []
    rules_md = root / RULES_MD
    if not rules_md.exists():
        violations.append(
            Violation(None, "render", f"{RULES_MD} is missing", RENDER_FIX)
        )
    elif rules_md.read_text() != render_rules_md(registry):
        violations.append(Violation(None, "render", f"{RULES_MD} is stale", RENDER_FIX))
    agents = root / AGENTS_MD
    block = extract_block(agents.read_text()) if agents.exists() else None
    if block is None:
        violations.append(
            Violation(
                None, "render", f"{AGENTS_MD} has no generated rules block", RENDER_FIX
            )
        )
    elif block != render_agents_block(registry):
        violations.append(
            Violation(
                None, "render", f"the rules block in {AGENTS_MD} is stale", RENDER_FIX
            )
        )
    return violations


def run_guard(
    root: Path = REPO_ROOT,
    *,
    base_ref: str | None = None,
    today: date | None = None,
    compare_base: bool = True,
) -> GuardResult:
    clear_caches()
    result = GuardResult()
    registry, schema_violations = load_registry(root)
    result.violations += schema_violations
    if registry is None:
        return result

    result.violations += validate(registry, root, today or date.today())
    for rule in registry.rules:
        result.violations += resolve_enforcer(rule, root)
        result.violations += resolve_ci(rule, root)
        result.violations += resolve_proof_ci(rule, root)
    result.violations += discover_hidden(registry, root)
    if registry.agents is not None:
        result.violations += check_adapters(registry.agents, root)
    result.violations += _stale_outputs(registry, root)

    ref = base_ref or default_base_ref()
    if not compare_base:
        return result
    if ref is None:
        result.notes.append(
            "no base ref (set --base-ref or GITHUB_BASE_REF); baseline comparison skipped"
        )
    else:
        try:
            base = load_base_registry(root, ref)
        except BaseUnavailable:
            if os.environ.get("GITHUB_ACTIONS"):
                result.violations.append(
                    Violation(
                        None,
                        "baseline",
                        f"base ref {ref} is not available",
                        "check out with fetch-depth: 0",
                    )
                )
            else:
                result.notes.append(
                    f"base ref {ref} is not available; baseline comparison skipped"
                )
        else:
            if base is None:
                result.notes.append(
                    f"{ref} has no registry yet; baseline comparison skipped"
                )
            else:
                violations, notes = check_baselines(registry, base)
                result.violations += violations
                result.notes += notes
    return result


def check() -> list[str]:
    """Adapter for scripts/run_quality_guards.py."""
    return [str(v) for v in run_guard(REPO_ROOT).violations]
