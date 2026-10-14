"""Load ``rules/registry.toml`` into the typed model.

Parsing reports structural problems (wrong types, unknown keys, bad enum values)
as violations instead of raising, so one run shows every problem at once.
"""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Any

from scripts.rules.model import (
    Baseline,
    Category,
    CiRef,
    Discovery,
    Enforcer,
    Ignored,
    Kind,
    Proof,
    Registry,
    Rule,
    RuleException,
    Status,
    Tier,
    Violation,
)

REGISTRY_PATH = Path("rules/registry.toml")

_TOP_KEYS = {"schema_version", "repo", "category", "discovery", "rule"}
_RULE_KEYS = {
    "id",
    "category",
    "statement",
    "rationale",
    "scope",
    "tier",
    "status",
    "autofix",
    "review_by",
    "enforcer",
    "ci",
    "proof",
    "baseline",
    "exception",
    "downgrade",
}
_DISCOVERY_KEYS = {
    "workflows",
    "guard_test_globs",
    "extra_guard_tests",
    "ignore_jobs",
    "ignore_tests",
}


class _Collector:
    def __init__(self) -> None:
        self.violations: list[Violation] = []

    def add(self, rule_id: str | None, message: str, fix: str) -> None:
        self.violations.append(Violation(rule_id, "schema", message, fix))

    def unknown_keys(
        self, rule_id: str | None, table: dict[str, Any], allowed: set[str], where: str
    ) -> None:
        for key in sorted(set(table) - allowed):
            self.add(
                rule_id,
                f"unknown key '{key}' in {where}",
                f"remove it or use one of {sorted(allowed)}",
            )

    def string(
        self, rule_id: str | None, table: dict[str, Any], key: str, where: str
    ) -> str:
        value = table.get(key)
        if isinstance(value, str) and value.strip():
            return value
        self.add(rule_id, f"{where}.{key} must be a non-empty string", f"set {key}")
        return ""

    def string_list(
        self,
        rule_id: str | None,
        table: dict[str, Any],
        key: str,
        where: str,
        *,
        required: bool = True,
    ) -> tuple[str, ...]:
        value = table.get(key)
        if value is None and not required:
            return ()
        if (
            isinstance(value, list)
            and all(isinstance(item, str) and item for item in value)
            and (value or not required)
        ):
            return tuple(value)
        self.add(
            rule_id,
            f"{where}.{key} must be a non-empty list of strings",
            f'set {key} = ["..."]',
        )
        return ()

    def enum(self, rule_id: str | None, enum_type: Any, value: Any, where: str) -> Any:
        try:
            return enum_type(value)
        except ValueError:
            allowed = [member.value for member in enum_type]
            self.add(rule_id, f"{where} is {value!r}", f"use one of {allowed}")
            return None

    def day(self, rule_id: str | None, value: Any, where: str) -> date | None:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                pass
        self.add(rule_id, f"{where} must be a date", "write it as YYYY-MM-DD")
        return None


def _ignored(c: _Collector, raw: Any, key: str, field: str) -> tuple[Ignored, ...]:
    if raw is None:
        return ()
    items = []
    for entry in raw if isinstance(raw, list) else [raw]:
        if (
            isinstance(entry, dict)
            and isinstance(entry.get(field), str)
            and isinstance(entry.get("reason"), str)
            and entry["reason"].strip()
        ):
            items.append(Ignored(entry[field], entry["reason"]))
        else:
            c.add(
                None,
                f"discovery.{key} entries need '{field}' and a non-empty 'reason'",
                f'write {{ {field} = "...", reason = "..." }}',
            )
    return tuple(items)


def _discovery(c: _Collector, raw: Any) -> Discovery:
    if raw is None:
        return Discovery()
    if not isinstance(raw, dict):
        c.add(None, "discovery must be a table", "write [discovery]")
        return Discovery()
    c.unknown_keys(None, raw, _DISCOVERY_KEYS, "discovery")
    workflows = c.string_list(None, raw, "workflows", "discovery", required=False)
    return Discovery(
        workflows=workflows or Discovery().workflows,
        guard_test_globs=c.string_list(
            None, raw, "guard_test_globs", "discovery", required=False
        ),
        extra_guard_tests=c.string_list(
            None, raw, "extra_guard_tests", "discovery", required=False
        ),
        ignore_jobs=_ignored(c, raw.get("ignore_jobs"), "ignore_jobs", "job"),
        ignore_tests=_ignored(c, raw.get("ignore_tests"), "ignore_tests", "node"),
    )


def _rule(c: _Collector, raw: Any, index: int) -> Rule | None:
    if not isinstance(raw, dict):
        c.add(None, f"rule #{index + 1} must be a table", "write [[rule]]")
        return None
    rule_id = raw.get("id") if isinstance(raw.get("id"), str) else None
    label = rule_id or f"rule #{index + 1}"
    c.unknown_keys(rule_id, raw, _RULE_KEYS, label)

    enforcer_raw = raw.get("enforcer")
    enforcer = Enforcer(Kind.NONE)
    if isinstance(enforcer_raw, dict):
        kind = c.enum(rule_id, Kind, enforcer_raw.get("kind"), f"{label}.enforcer.kind")
        fields = {k: v for k, v in enforcer_raw.items() if k != "kind"}
        enforcer = Enforcer(kind or Kind.NONE, fields)
    else:
        c.add(rule_id, f"{label}.enforcer must be a table", "add [rule.enforcer]")

    ci_refs = []
    ci_raw = raw.get("ci", [])
    for entry in ci_raw if isinstance(ci_raw, list) else [ci_raw]:
        if not isinstance(entry, dict):
            c.add(rule_id, f"{label}.ci entries must be tables", "write [[rule.ci]]")
            continue
        c.unknown_keys(rule_id, entry, {"workflow", "job", "invocation"}, f"{label}.ci")
        ci_refs.append(
            CiRef(
                c.string(rule_id, entry, "workflow", f"{label}.ci"),
                c.string(rule_id, entry, "job", f"{label}.ci"),
                c.string(rule_id, entry, "invocation", f"{label}.ci"),
            )
        )

    proof = None
    if "proof" in raw:
        if isinstance(raw["proof"], dict):
            proof = Proof(dict(raw["proof"]))
        else:
            c.add(rule_id, f"{label}.proof must be a table", "write [rule.proof]")

    baseline = None
    if "baseline" in raw:
        braw = raw["baseline"]
        if isinstance(braw, dict) and isinstance(braw.get("count"), int):
            c.unknown_keys(rule_id, braw, {"file", "count"}, f"{label}.baseline")
            baseline = Baseline(
                c.string(rule_id, braw, "file", f"{label}.baseline"), braw["count"]
            )
        else:
            c.add(
                rule_id,
                f"{label}.baseline needs 'file' and an integer 'count'",
                "write [rule.baseline] with file and count",
            )

    exceptions = []
    exc_raw = raw.get("exception", [])
    for entry in exc_raw if isinstance(exc_raw, list) else [exc_raw]:
        if not isinstance(entry, dict):
            c.add(
                rule_id,
                f"{label}.exception entries must be tables",
                "write [[rule.exception]]",
            )
            continue
        c.unknown_keys(
            rule_id, entry, {"path", "reason", "expires"}, f"{label}.exception"
        )
        expires = c.day(rule_id, entry.get("expires"), f"{label}.exception.expires")
        exceptions.append(
            RuleException(
                c.string(rule_id, entry, "path", f"{label}.exception"),
                c.string(rule_id, entry, "reason", f"{label}.exception"),
                expires or date.max,
            )
        )

    downgrade_reason = None
    if "downgrade" in raw:
        draw = raw["downgrade"]
        if isinstance(draw, dict) and isinstance(draw.get("reason"), str):
            downgrade_reason = draw["reason"]
        else:
            c.add(
                rule_id,
                f"{label}.downgrade needs a 'reason'",
                'write [rule.downgrade] reason = "..."',
            )

    autofix = raw.get("autofix")
    if not isinstance(autofix, bool):
        c.add(rule_id, f"{label}.autofix must be true or false", "set autofix")
        autofix = False

    review_by = None
    if "review_by" in raw:
        review_by = c.day(rule_id, raw["review_by"], f"{label}.review_by")

    tier = c.enum(rule_id, Tier, raw.get("tier"), f"{label}.tier")
    status = c.enum(rule_id, Status, raw.get("status"), f"{label}.status")
    if tier is None or status is None:
        return None

    return Rule(
        id=c.string(rule_id, raw, "id", label),
        category=c.string(rule_id, raw, "category", label),
        statement=c.string(rule_id, raw, "statement", label),
        rationale=c.string(rule_id, raw, "rationale", label),
        scope=c.string_list(rule_id, raw, "scope", label),
        tier=tier,
        status=status,
        autofix=autofix,
        enforcer=enforcer,
        ci=tuple(ci_refs),
        review_by=review_by,
        proof=proof,
        baseline=baseline,
        exceptions=tuple(exceptions),
        downgrade_reason=downgrade_reason,
    )


def parse(raw: dict[str, Any]) -> tuple[Registry | None, list[Violation]]:
    """Turn raw TOML data into a ``Registry``, collecting every schema problem."""
    c = _Collector()
    c.unknown_keys(None, raw, _TOP_KEYS, "registry")

    schema_version = raw.get("schema_version")
    if schema_version != 1:
        c.add(None, f"schema_version is {schema_version!r}", "set schema_version = 1")

    categories = []
    for entry in raw.get("category", []):
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            c.unknown_keys(None, entry, {"id", "title"}, f"category {entry['id']}")
            categories.append(
                Category(entry["id"], c.string(None, entry, "title", "category"))
            )
        else:
            c.add(
                None,
                "each [[category]] needs an id and title",
                "fix the category table",
            )

    rules = [_rule(c, entry, i) for i, entry in enumerate(raw.get("rule", []))]

    registry = Registry(
        schema_version=1,
        repo=c.string(None, raw, "repo", "registry"),
        categories=tuple(categories),
        discovery=_discovery(c, raw.get("discovery")),
        rules=tuple(rule for rule in rules if rule is not None),
    )
    return registry, c.violations


def load_text(text: str) -> tuple[Registry | None, list[Violation]]:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        return None, [
            Violation(
                None,
                "schema",
                f"registry is not valid TOML ({error})",
                "fix the TOML syntax",
            )
        ]
    return parse(raw)


def load_registry(root: Path) -> tuple[Registry | None, list[Violation]]:
    path = root / REGISTRY_PATH
    if not path.exists():
        return None, [
            Violation(
                None, "schema", f"{REGISTRY_PATH} is missing", f"create {REGISTRY_PATH}"
            )
        ]
    return load_text(path.read_text())
