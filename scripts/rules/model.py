"""Data model for the rules registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any


class Tier(StrEnum):
    MECHANICAL = "mechanical"
    METRIC = "metric"
    JUDGMENT = "judgment"


class Status(StrEnum):
    ENFORCED = "enforced"
    RATCHETED = "ratcheted"
    ADVISORY = "advisory"
    DOC_ONLY = "doc-only"


class Kind(StrEnum):
    PYTEST = "pytest"
    QUALITY_GUARD = "quality-guard"
    RUFF = "ruff"
    MYPY = "mypy"
    PYRIGHT = "pyright"
    IMPORT_LINTER = "import-linter"
    WORKFLOW_JOB = "workflow-job"
    DOCS_GUARD = "docs-guard"
    LLM_REVIEW = "llm-review"
    NONE = "none"


@dataclass(frozen=True)
class Violation:
    """One guard failure. ``fix`` always tells the reader what to do next."""

    rule_id: str | None
    check: str
    message: str
    fix: str

    def __str__(self) -> str:
        subject = self.rule_id or "registry"
        return f"[{subject}] {self.check}: {self.message}. Fix: {self.fix}."


@dataclass(frozen=True)
class Category:
    id: str
    title: str


@dataclass(frozen=True)
class Ignored:
    """A discovered item deliberately left out of the registry."""

    target: str
    reason: str


@dataclass(frozen=True)
class Discovery:
    workflows: tuple[str, ...] = (".github/workflows/pr.yml",)
    guard_test_globs: tuple[str, ...] = ()
    extra_guard_tests: tuple[str, ...] = ()
    ignore_jobs: tuple[Ignored, ...] = ()
    ignore_tests: tuple[Ignored, ...] = ()


@dataclass(frozen=True)
class Agents:
    """Agent instruction files: one source, plus thin per-tool adapters."""

    instructions: str
    adapters: tuple[str, ...]
    max_adapter_lines: int = 20


@dataclass(frozen=True)
class CiScripts:
    """Where workflow scripts live, where their tests are, and their baselines."""

    workflows: str
    scripts_dir: str
    test_globs: tuple[str, ...]
    multiline_baseline: str
    untested_baseline: str
    shellcheck_baseline: str


@dataclass(frozen=True)
class Enforcer:
    kind: Kind
    fields: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)

    @property
    def description(self) -> str:
        """Short human-readable description of what enforces the rule."""
        kind, fields = self.kind, self.fields
        if kind is Kind.PYTEST:
            prefix = f"{fields['project'].rstrip('/')}/" if "project" in fields else ""
            files = sorted({node.split("::", 1)[0] for node in fields.get("nodes", [])})
            return "pytest " + ", ".join(f"`{prefix}{path}`" for path in files)
        if kind is Kind.QUALITY_GUARD:
            return f"quality guard `{fields.get('name', '')}`"
        if kind is Kind.RUFF:
            codes = ", ".join(fields.get("codes", []))
            mode = fields.get("mode", "")
            if mode == "format":
                return "ruff format"
            if mode == "per-file-ignore":
                return (
                    f"ruff per-file ignore of {codes} for `{fields.get('pattern', '')}`"
                )
            return f"ruff check ({codes})"
        if kind is Kind.MYPY:
            return "mypy"
        if kind is Kind.WORKFLOW_JOB:
            return "CI job"
        if kind in (Kind.PYRIGHT, Kind.IMPORT_LINTER):
            return f"{kind.value} `{fields.get('config', '')}`"
        if kind is Kind.DOCS_GUARD:
            return f"docs guard on `{fields.get('doc', '')}`"
        if kind is Kind.LLM_REVIEW:
            return f"LLM review with `{fields.get('prompt', '')}`"
        return "nothing"

    @property
    def expects_proof(self) -> bool:
        """Custom checkers need proof; third-party tools and CI jobs are the check."""
        return self.kind in (
            Kind.PYTEST,
            Kind.QUALITY_GUARD,
            Kind.DOCS_GUARD,
            Kind.IMPORT_LINTER,
            Kind.LLM_REVIEW,
        )


@dataclass(frozen=True)
class CiRef:
    workflow: str
    job: str
    invocation: str


@dataclass(frozen=True)
class Proof:
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class Baseline:
    file: str
    count: int


@dataclass(frozen=True)
class RuleException:
    path: str
    reason: str
    expires: date


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    statement: str
    rationale: str
    scope: tuple[str, ...]
    tier: Tier
    status: Status
    autofix: bool
    enforcer: Enforcer
    ci: tuple[CiRef, ...] = ()
    review_by: date | None = None
    proof: Proof | None = None
    baseline: Baseline | None = None
    exceptions: tuple[RuleException, ...] = ()
    downgrade_reason: str | None = None

    @property
    def blocking(self) -> bool:
        """Derived, never declared: whether a violation can fail a merge."""
        return (
            self.status in (Status.ENFORCED, Status.RATCHETED)
            and self.tier is not Tier.JUDGMENT
        )


@dataclass(frozen=True)
class Registry:
    schema_version: int
    repo: str
    categories: tuple[Category, ...]
    discovery: Discovery
    rules: tuple[Rule, ...]
    agents: Agents | None = None
    ci_scripts: CiScripts | None = None

    def rule(self, rule_id: str) -> Rule | None:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None
