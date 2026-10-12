"""The ci-scripts quality guard: workflow logic lives in tested shell scripts.

Three checks, each ratcheted against a baseline file listed in ``[ci_scripts]``:

1. A workflow ``run:`` block holds at most one logical line of code.
2. Every shell script a workflow calls is referenced by at least one test.
3. Every shell script in the scripts directory passes ``shellcheck``.

Anything found that isn't in the baseline fails, and so does a baseline entry
that no longer applies, so baselines only shrink.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from scripts.rules.load import load_registry
from scripts.rules.model import CiScripts, Registry, Violation
from scripts.rules.resolve import clear_caches, workflow_jobs

REPO_ROOT = Path(__file__).resolve().parents[2]
SEPARATOR = " :: "


@dataclass
class Findings:
    multiline: set[str] = field(default_factory=set)
    untested: set[str] = field(default_factory=set)
    shellcheck: set[str] | None = None  # None when shellcheck could not run
    notes: list[str] = field(default_factory=list)


def multiline_runs(config: CiScripts, root: Path) -> set[str]:
    """``workflow :: job :: step`` for every run: block over one logical line."""
    found = set()
    for workflow in sorted(root.glob(config.workflows)):
        relative = workflow.relative_to(root).as_posix()
        for job in workflow_jobs(workflow)[0].values():
            for block in job.run_blocks:
                if block.code_lines > 1:
                    found.add(SEPARATOR.join((relative, job.id, block.step)))
    return found


def called_scripts(config: CiScripts, root: Path) -> set[str]:
    """Shell scripts in the scripts directory that a workflow calls."""
    pattern = re.compile(re.escape(config.scripts_dir.rstrip("/")) + r"/[\w.-]+\.sh")
    called = set()
    for workflow in root.glob(config.workflows):
        for job in workflow_jobs(workflow)[0].values():
            called.update(pattern.findall(job.run_text))
    return {path for path in called if (root / path).is_file()}


def untested_scripts(config: CiScripts, root: Path) -> set[str]:
    """Called scripts whose file name appears in no test file."""
    tests = [
        path.read_text(errors="replace")
        for pattern in config.test_globs
        for path in root.glob(pattern)
        if path.is_file() and ".venv" not in path.parts
    ]
    return {
        script
        for script in called_scripts(config, root)
        if not any(Path(script).name in text for text in tests)
    }


def shellcheck_failures(config: CiScripts, root: Path) -> set[str] | None:
    """Scripts with any shellcheck finding, or None if shellcheck isn't installed."""
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        return None
    scripts = sorted(
        path.relative_to(root).as_posix()
        for path in (root / config.scripts_dir).glob("*.sh")
    )
    if not scripts:
        return set()
    result = subprocess.run(
        [shellcheck, "--format=gcc", *scripts],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return {line.split(":", 1)[0] for line in result.stdout.splitlines() if ":" in line}


def find(config: CiScripts, root: Path) -> Findings:
    clear_caches()
    findings = Findings(
        multiline=multiline_runs(config, root),
        untested=untested_scripts(config, root),
        shellcheck=shellcheck_failures(config, root),
    )
    if findings.shellcheck is None:
        findings.notes.append(
            "shellcheck is not installed; the shellcheck check was skipped"
        )
    return findings


def _baseline(root: Path, path: str) -> set[str]:
    file = root / path
    if not file.is_file():
        return set()
    return {
        line.strip()
        for line in file.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _rule_for(registry: Registry, baseline: str) -> str | None:
    for rule in registry.rules:
        if rule.baseline is not None and rule.baseline.file == baseline:
            return rule.id
    return None


def compare(registry: Registry, findings: Findings, root: Path) -> list[Violation]:
    config = registry.ci_scripts
    assert config is not None
    checks = (
        (
            "multi-line run: block",
            findings.multiline,
            config.multiline_baseline,
            "move the commands into a tested script under "
            f"{config.scripts_dir} and call it from a single-line run:",
        ),
        (
            "untested workflow script",
            findings.untested,
            config.untested_baseline,
            "add a test that runs the script (see docs/engineering/skills/ci-workflows.md)",
        ),
        (
            "shellcheck finding in",
            findings.shellcheck,
            config.shellcheck_baseline,
            "fix what `shellcheck <script>` reports",
        ),
    )
    violations = []
    for label, found, baseline_path, fix in checks:
        if found is None:
            continue
        rule_id = _rule_for(registry, baseline_path)
        baseline = _baseline(root, baseline_path)
        for entry in sorted(found - baseline):
            violations.append(Violation(rule_id, "ci-scripts", f"{label} {entry}", fix))
        for entry in sorted(baseline - found):
            violations.append(
                Violation(
                    rule_id,
                    "ci-scripts",
                    f"baseline entry no longer applies: {entry}",
                    f"remove it from {baseline_path} and lower the rule's baseline count",
                )
            )
    return violations


def write_baselines(registry: Registry, findings: Findings, root: Path) -> None:
    """Record today's findings as the baselines (used once, when adopting the rule)."""
    config = registry.ci_scripts
    assert config is not None
    for found, path in (
        (findings.multiline, config.multiline_baseline),
        (findings.untested, config.untested_baseline),
        (findings.shellcheck, config.shellcheck_baseline),
    ):
        if found is None:
            continue
        lines = [
            "# Tolerated existing violations. This list may only shrink.",
            *sorted(found),
        ]
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("\n".join(lines) + "\n")


def run_check(root: Path = REPO_ROOT) -> tuple[list[Violation], list[str]]:
    registry, violations = load_registry(root)
    if registry is None or registry.ci_scripts is None:
        return violations, [
            "no [ci_scripts] table in rules/registry.toml; nothing to check"
        ]
    findings = find(registry.ci_scripts, root)
    violations = compare(registry, findings, root)
    if findings.shellcheck is None and os.environ.get("GITHUB_ACTIONS"):
        violations.append(
            Violation(
                _rule_for(registry, registry.ci_scripts.shellcheck_baseline),
                "ci-scripts",
                "shellcheck is not installed in this CI job",
                "install it in the job (pip install shellcheck-py==<version>)",
            )
        )
    return violations, findings.notes


def check() -> list[str]:
    """Adapter for scripts/run_quality_guards.py."""
    violations, notes = run_check(REPO_ROOT)
    for note in notes:
        print(f"note: {note}")
    return [str(violation) for violation in violations]
