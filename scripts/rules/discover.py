"""Find rules that are enforced somewhere but missing from the registry.

A check that isn't registered is a hidden rule: nobody can see it in
``rules.md`` and agents aren't told about it. This scans the places checks live
today and requires each one to be referenced by a rule, or ignored with a
reason in ``[discovery]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.rules.model import Kind, Registry, Violation
from scripts.rules.resolve import (
    DEFAULT_RUNNER,
    guard_names,
    mypy_files,
    root_relative_nodes,
    ruff_lint_config,
    split_node,
    test_names,
    workflow_jobs,
)

if TYPE_CHECKING:
    from pathlib import Path


def _hidden(message: str, fix: str) -> Violation:
    return Violation(None, "hidden-rule", message, fix)


def _registered_nodes(registry: Registry) -> set[str]:
    nodes = set()
    for rule in registry.rules:
        if rule.enforcer.kind is Kind.PYTEST:
            for node in root_relative_nodes(rule):
                path, name = split_node(node)
                nodes.add(f"{path}::{name}")
        if rule.proof is not None and isinstance(rule.proof.fields.get("test"), str):
            project = rule.proof.fields.get("project")
            prefix = f"{project.rstrip('/')}/" if isinstance(project, str) else ""
            path, name = split_node(prefix + rule.proof.fields["test"])
            nodes.add(f"{path}::{name}")
    return nodes


def _discovered_tests(registry: Registry, root: Path) -> set[str]:
    found = set()
    for pattern in registry.discovery.guard_test_globs:
        for path in sorted(root.glob(pattern)):
            names = test_names(path)
            relative = path.relative_to(root).as_posix()
            for name in names or ():
                found.add(f"{relative}::{name}")
    for node in registry.discovery.extra_guard_tests:
        path, name = split_node(node)
        found.add(f"{path}::{name}")
    return found


def discover_hidden(registry: Registry, root: Path) -> list[Violation]:
    """Return a hidden-rule violation for each check no rule references or ignores."""
    violations = []
    rules = registry.rules

    # Quality guards registered in the runner.
    names = guard_names(root, DEFAULT_RUNNER) or []
    registered = {
        r.enforcer.get("name") for r in rules if r.enforcer.kind is Kind.QUALITY_GUARD
    }
    for name in names:
        if name not in registered:
            violations.append(
                _hidden(
                    f"quality guard '{name}' in {DEFAULT_RUNNER} has no rule",
                    'add a [[rule]] with enforcer.kind = "quality-guard"',
                )
            )

    # Ruff: format checks in CI, explicitly selected codes, per-file ignores.
    ruff_rules = [r for r in rules if r.enforcer.kind is Kind.RUFF]
    runs_format = any(
        "ruff format" in job.run_text
        for workflow in registry.discovery.workflows
        for job in workflow_jobs(root / workflow)[0].values()
    )
    if runs_format and not any(r.enforcer.get("mode") == "format" for r in ruff_rules):
        violations.append(
            _hidden(
                "CI runs 'ruff format' but no rule describes it",
                "add a ruff format rule",
            )
        )
    lint = ruff_lint_config(root)
    lint_codes = {
        c
        for r in ruff_rules
        if r.enforcer.get("mode") == "lint"
        for c in r.enforcer.get("codes", [])
    }
    for code in list(lint.get("select", [])) + list(lint.get("extend-select", [])):
        if code not in lint_codes:
            violations.append(
                _hidden(
                    f"ruff selects '{code}' but no rule describes it",
                    "add the code to a ruff lint rule",
                )
            )
    ignore_patterns = {
        r.enforcer.get("pattern")
        for r in ruff_rules
        if r.enforcer.get("mode") == "per-file-ignore"
    }
    for pattern in lint.get("per-file-ignores", {}):
        if pattern not in ignore_patterns:
            violations.append(
                _hidden(
                    f"ruff per-file-ignores '{pattern}' has no rule",
                    "add a ruff per-file-ignore rule explaining the exemption",
                )
            )

    # mypy scope.
    covered = {
        p
        for r in rules
        if r.enforcer.kind is Kind.MYPY
        for p in r.enforcer.get("paths", [])
    }
    for path in mypy_files(root):
        if path not in covered:
            violations.append(
                _hidden(
                    f"mypy checks '{path}' but no rule describes it",
                    "add it to a mypy rule's paths",
                )
            )

    # Guard-style tests.
    registered_nodes = _registered_nodes(registry)
    ignored_tests = {
        split_node(i.target)[0] + "::" + split_node(i.target)[1]
        for i in registry.discovery.ignore_tests
    }
    for node in sorted(
        _discovered_tests(registry, root) - registered_nodes - ignored_tests
    ):
        violations.append(
            _hidden(
                f"guard test {node} is not referenced by any rule",
                "add it to a pytest rule's nodes, or to discovery.ignore_tests with a reason",
            )
        )

    # CI jobs.
    referenced_jobs = {(ref.workflow, ref.job) for r in rules for ref in r.ci}
    ignored_jobs = {i.target for i in registry.discovery.ignore_jobs}
    for workflow in registry.discovery.workflows:
        for job_id in workflow_jobs(root / workflow)[0]:
            if (workflow, job_id) not in referenced_jobs and job_id not in ignored_jobs:
                violations.append(
                    _hidden(
                        f"CI job '{job_id}' in {workflow} enforces no registered rule",
                        "reference it from a rule's [[rule.ci]], or add it to discovery.ignore_jobs with a reason",
                    )
                )
    return violations
