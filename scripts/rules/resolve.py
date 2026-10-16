"""Check that each rule's enforcer and CI wiring really exist.

Everything here reads files statically (``ast``, ``tomllib`` and the workflow
subset reader) so it needs no project dependencies and never imports project
code.
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

from scripts.rules.file_exceptions import (
    linted_files,
    matching_files,
    out_of_scope_files,
)
from scripts.rules.model import CiRef, Kind, Rule, Violation
from scripts.rules.workflows import JobBlock, parse_jobs

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

DEFAULT_RUNNER = "scripts/run_quality_guards.py"
RUFF_DEFAULT_SELECT = ("E4", "E7", "E9", "F")
PROOF_CI_FIELDS = ("workflow", "job", "invocation")
# How many offending files a file-level exception violation names.
SHOWN_OUT_OF_SCOPE_FILES = 3


# --- shared readers -------------------------------------------------------


@cache
def _read(path: Path) -> str | None:
    return path.read_text() if path.is_file() else None


def clear_caches() -> None:
    """Forget cached file reads and parses, so the next check sees the files afresh."""
    _read.cache_clear()
    workflow_jobs.cache_clear()
    test_names.cache_clear()
    linted_files.cache_clear()


@cache
def workflow_jobs(path: Path) -> tuple[dict[str, JobBlock], tuple[str, ...]]:
    """Return a workflow's jobs by id and its parse problems; cached per path."""
    text = _read(path)
    if text is None:
        return {}, (f"{path.name} is missing",)
    jobs, problems = parse_jobs(text)
    return jobs, tuple(problems)


@cache
def test_names(path: Path) -> frozenset[str] | None:
    """Pytest-collectable names in a file: ``func`` and ``Class::method``."""
    text = _read(path)
    if text is None:
        return None
    names = set()
    for node in ast.parse(text).body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.name.startswith("test"):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(
                    item, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and item.name.startswith("test"):
                    names.add(f"{node.name}::{item.name}")
    return frozenset(names)


def split_node(node: str) -> tuple[str, str]:
    """``path::name[param]`` -> (``path``, ``name``)."""
    path, _, name = node.partition("::")
    return path, re.sub(r"\[.*\]$", "", name)


def root_relative_nodes(rule: Rule) -> list[str]:
    """Pytest nodes of a rule, prefixed with the project directory if any."""
    project = rule.enforcer.get("project")
    nodes = rule.enforcer.get("nodes", [])
    prefix = f"{project.rstrip('/')}/" if project else ""
    return [f"{prefix}{node}" for node in nodes]


def node_exists(root: Path, node: str) -> str | None:
    """Return a problem description, or None if the node resolves."""
    path, name = split_node(node)
    if not name:
        return f"'{node}' has no '::test_name' part"
    names = test_names(root / path)
    if names is None:
        return f"test file {path} does not exist"
    if name not in names:
        return f"{path} has no test '{name}'"
    return None


def guard_names(root: Path, runner: str = DEFAULT_RUNNER) -> list[str] | None:
    """Return the string names in the runner's ``GUARDS`` tuple.

    Return None if the runner is missing, and an empty list if it has no ``GUARDS``.
    """
    text = _read(root / runner)
    if text is None:
        return None
    for node in ast.parse(text).body:
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and target.id == "GUARDS"
            and isinstance(value, ast.Tuple)
        ):
            return [
                element.elts[0].value
                for element in value.elts
                if (
                    isinstance(element, ast.Tuple)
                    and element.elts
                    and isinstance(element.elts[0], ast.Constant)
                    and isinstance(element.elts[0].value, str)
                )
            ]
    return []


def _toml(path: Path) -> dict[str, Any]:
    text = _read(path)
    return tomllib.loads(text) if text else {}


def ruff_lint_config(root: Path) -> dict[str, Any]:
    """Return ruff.toml's ``lint`` table, else ``[tool.ruff.lint]`` in pyproject."""
    ruff_toml = _toml(root / "ruff.toml")
    if ruff_toml:
        return ruff_toml.get("lint", {})
    return (
        _toml(root / "pyproject.toml").get("tool", {}).get("ruff", {}).get("lint", {})
    )


def ruff_selected(root: Path) -> tuple[str, ...]:
    """Return ruff's ``select`` (its default when unset) plus ``extend-select``."""
    lint = ruff_lint_config(root)
    selected = tuple(lint.get("select", RUFF_DEFAULT_SELECT))
    return selected + tuple(lint.get("extend-select", ()))


def mypy_files(root: Path) -> list[str]:
    """Return ``[tool.mypy].files`` as a list, even when it is a single string."""
    files = (
        _toml(root / "pyproject.toml").get("tool", {}).get("mypy", {}).get("files", [])
    )
    return [files] if isinstance(files, str) else list(files)


def make_target_paths(root: Path, target: str) -> list[str] | None:
    """Pytest path arguments in a Makefile target's recipe."""
    text = _read(root / "Makefile")
    if text is None:
        return None
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(target)}\s*:", line):
            recipe = []
            for body in lines[index + 1 :]:
                if not body.startswith("\t"):
                    break
                recipe.append(body)
            paths = []
            for body in recipe:
                if "pytest" not in body:
                    continue
                tokens = body.split("pytest", 1)[1].split()
                paths += [
                    t
                    for t in tokens
                    if not t.startswith("-") and ("/" in t or t.endswith(".py"))
                ]
            return paths
    return None


# --- per-kind resolvers ---------------------------------------------------


def _v(rule: Rule, message: str, fix: str) -> Violation:
    return Violation(rule.id, "enforcer", message, fix)


def _resolve_pytest(rule: Rule, root: Path) -> list[Violation]:
    violations = []
    project = rule.enforcer.get("project")
    if project and not (root / project).is_dir():
        violations.append(
            _v(
                rule,
                f"project directory {project} does not exist",
                "fix enforcer.project",
            )
        )
    for node in root_relative_nodes(rule):
        problem = node_exists(root, node)
        if problem:
            violations.append(
                _v(
                    rule,
                    problem,
                    "point enforcer.nodes at an existing test, or restore the test",
                )
            )
    return violations


def _resolve_quality_guard(rule: Rule, root: Path) -> list[Violation]:
    runner = rule.enforcer.get("runner", DEFAULT_RUNNER)
    names = guard_names(root, runner)
    if names is None:
        return [
            _v(rule, f"guard runner {runner} does not exist", "fix enforcer.runner")
        ]
    name = rule.enforcer.get("name")
    if name not in names:
        return [
            _v(
                rule,
                f"no guard named '{name}' in GUARDS of {runner}",
                f"use one of {names}",
            )
        ]
    return []


def _resolve_ruff(rule: Rule, root: Path) -> list[Violation]:
    mode = rule.enforcer.get("mode")
    codes = rule.enforcer.get("codes", [])
    if mode == "lint":
        selected = ruff_selected(root)
        missing = [
            code for code in codes if not any(code.startswith(s) for s in selected)
        ]
        if missing:
            return [
                _v(
                    rule,
                    f"ruff does not select {missing} (selected: {list(selected)})",
                    "add them to the ruff select list or fix enforcer.codes",
                )
            ]
    elif mode == "per-file-ignore":
        ignores = ruff_lint_config(root).get("per-file-ignores", {})
        pattern = rule.enforcer.get("pattern")
        if sorted(ignores.get(pattern, [])) != sorted(codes):
            return [
                _v(
                    rule,
                    f"ruff per-file-ignores has no entry {pattern!r} = {codes}",
                    "match enforcer.pattern/codes to the ruff config",
                )
            ]
        return _file_level_exception_scope(rule, root, pattern)
    return []


def _file_level_exception_scope(
    rule: Rule, root: Path, pattern: str
) -> list[Violation]:
    """Check a per-file ignore covers only tests, CI/CD and command-line scripts."""
    out_of_scope = out_of_scope_files(root, pattern)
    if out_of_scope is None:
        return [
            _v(
                rule,
                f"ruff per-file-ignores pattern {pattern!r} is negated",
                "name the files the exception covers",
            )
        ]
    if not matching_files(root, pattern):
        return [
            _v(
                rule,
                f"ruff per-file-ignores pattern {pattern!r} matches no files",
                "fix the pattern, or remove the exception",
            )
        ]
    if out_of_scope:
        shown = ", ".join(out_of_scope[:SHOWN_OUT_OF_SCOPE_FILES])
        hidden = len(out_of_scope) - SHOWN_OUT_OF_SCOPE_FILES
        more = f" and {hidden} more" if hidden > 0 else ""
        return [
            _v(
                rule,
                f"ruff per-file-ignores {pattern!r} covers files that may not take "
                f"file-level exceptions: {shown}{more}",
                "file-level exceptions are only for tests, CI/CD scripts and "
                "command-line scripts; narrow the pattern and suppress other "
                "findings inline with a reason",
            )
        ]
    return []


def _resolve_mypy(rule: Rule, root: Path) -> list[Violation]:
    configured = mypy_files(root)
    missing = [p for p in rule.enforcer.get("paths", []) if p not in configured]
    if missing:
        return [
            _v(
                rule,
                f"{missing} not in [tool.mypy].files",
                "add them to [tool.mypy].files or fix enforcer.paths",
            )
        ]
    return []


def _resolve_file_field(field_name: str) -> Callable[[Rule, Path], list[Violation]]:
    def resolve(rule: Rule, root: Path) -> list[Violation]:
        value = rule.enforcer.get(field_name)
        if value and not (root / value).exists():
            return [
                _v(
                    rule,
                    f"{field_name} file {value} does not exist",
                    f"create it or fix enforcer.{field_name}",
                )
            ]
        return []

    return resolve


def _resolve_workflow_job(rule: Rule, root: Path) -> list[Violation]:
    step = rule.enforcer.get("step")
    if not step:
        return []
    violations = []
    for ref in rule.ci:
        job = workflow_jobs(root / ref.workflow)[0].get(ref.job)
        if job and not any(step in name for name in job.step_names):
            violations.append(
                _v(
                    rule,
                    f"job '{ref.job}' has no step named like '{step}'",
                    "fix enforcer.step",
                )
            )
    return violations


RESOLVERS: dict[Kind, Callable[[Rule, Path], list[Violation]]] = {
    Kind.PYTEST: _resolve_pytest,
    Kind.QUALITY_GUARD: _resolve_quality_guard,
    Kind.RUFF: _resolve_ruff,
    Kind.MYPY: _resolve_mypy,
    Kind.PYRIGHT: _resolve_file_field("config"),
    Kind.IMPORT_LINTER: _resolve_file_field("config"),
    Kind.WORKFLOW_JOB: _resolve_workflow_job,
    Kind.DOCS_GUARD: _resolve_file_field("doc"),
    Kind.LLM_REVIEW: _resolve_file_field("prompt"),
    Kind.NONE: lambda _rule, _root: [],
}


def resolve_enforcer(rule: Rule, root: Path) -> list[Violation]:
    """Check that the rule's enforcer exists where its kind says it should."""
    return RESOLVERS[rule.enforcer.kind](rule, root)


# --- CI wiring ------------------------------------------------------------


def _job_for(
    rule_id: str, ref: CiRef, root: Path, check: str, field: str
) -> tuple[JobBlock | None, list[Violation]]:
    """Return the job a CI reference names if it runs the invocation, plus problems."""

    def v(message: str, fix: str) -> Violation:
        return Violation(rule_id, check, message, fix)

    if not (root / ref.workflow).is_file():
        return None, [
            v(f"workflow {ref.workflow} does not exist", f"fix {field}.workflow")
        ]
    jobs, problems = workflow_jobs(root / ref.workflow)
    violations = [
        v(
            f"{ref.workflow}: {problem}",
            "keep workflows within the supported YAML subset",
        )
        for problem in problems
    ]
    job = jobs.get(ref.job)
    if job is None:
        violations.append(
            v(f"no job '{ref.job}' in {ref.workflow}", f"use one of {sorted(jobs)}")
        )
        return None, violations
    if not job.invokes(ref.invocation):
        violations.append(
            v(
                f"job '{ref.job}' in {ref.workflow} does not run '{ref.invocation}'",
                f"correct {field}.invocation, or make the job run it",
            )
        )
        return None, violations
    return job, violations


def resolve_ci(rule: Rule, root: Path) -> list[Violation]:
    """Each CI reference names a real job that really runs the enforcer."""
    violations = []
    for ref in rule.ci:
        job, problems = _job_for(rule.id, ref, root, "ci", "rule.ci")
        violations += problems
        if job is not None and rule.enforcer.kind is Kind.PYTEST:
            required = _RequiredTests(
                rule_id=rule.id,
                check="ci",
                nodes=root_relative_nodes(rule),
                project=rule.enforcer.get("project"),
            )
            violations += _test_coverage(required, ref.invocation, job, root)
    return violations


def resolve_proof_ci(rule: Rule, root: Path) -> list[Violation]:
    """Check that a CI job collects the rule's proof test.

    Without that, nothing shows the checker still works. The proof test itself
    asserts that the bad fixture is rejected and the good one accepted; the
    guard checks that some CI job collects it. A proof runs in the rule's own
    CI job when the rule is pytest-enforced; otherwise the proof names its job
    with ``workflow``, ``job`` and ``invocation``.
    """
    if rule.proof is None or not isinstance(rule.proof.fields.get("test"), str):
        return []
    fields = rule.proof.fields
    project = fields.get("project") if isinstance(fields.get("project"), str) else None
    prefix = f"{project.rstrip('/')}/" if project else ""
    node = prefix + fields["test"]
    if all(isinstance(fields.get(key), str) for key in PROOF_CI_FIELDS):
        refs = [CiRef(fields["workflow"], fields["job"], fields["invocation"])]
    elif rule.enforcer.kind is Kind.PYTEST:
        refs = list(rule.ci)
    else:
        refs = []
    if not refs:
        return [
            Violation(
                rule.id,
                "proof",
                "the proof test is not tied to a CI job",
                "add proof.workflow, proof.job and proof.invocation naming the "
                "job that runs it",
            )
        ]
    violations = []
    for ref in refs:
        job, problems = _job_for(rule.id, ref, root, "proof", "proof")
        violations += problems
        if job is not None:
            required = _RequiredTests(
                rule_id=rule.id, check="proof", nodes=[node], project=project
            )
            violations += _test_coverage(required, ref.invocation, job, root)
    return violations


@dataclass(frozen=True)
class _RequiredTests:
    """Root-relative test nodes a CI job must collect, and how to report a miss."""

    rule_id: str
    check: str
    nodes: list[str]
    project: str | None


def _test_coverage(
    required: _RequiredTests, invocation: str, job: JobBlock, root: Path
) -> list[Violation]:
    """Check that the job's test command collects the required test nodes.

    Only ``make`` targets and ``unittest discover`` commands are inspected; any
    other command is trusted.
    """
    violations = []
    collected: list[str] | None = None
    described = ""
    if invocation.startswith("make "):
        target = invocation.split()[1]
        collected = make_target_paths(root, target)
        described = f"'make {target}'"
    elif "unittest discover" in invocation:
        match = re.search(r"(?:-s|--start-directory)\s+(\S+)", invocation)
        collected = [match.group(1)] if match else None
        described = f"'{invocation}'"
    if collected:
        for node in required.nodes:
            path = split_node(node)[0]
            if not any(
                path == p or path.startswith(p.rstrip("/") + "/") for p in collected
            ):
                violations.append(
                    Violation(
                        required.rule_id,
                        required.check,
                        f"{path} is not collected by {described} "
                        f"(collects {collected})",
                        "add it to what the job runs, or move the test",
                    )
                )
    if (
        required.project
        and job.matrix
        and not any(required.project in values for values in job.matrix.values())
    ):
        violations.append(
            Violation(
                required.rule_id,
                required.check,
                f"project {required.project} is not in the matrix of job '{job.id}'",
                "add the project to the job matrix",
            )
        )
    return violations
