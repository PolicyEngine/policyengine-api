"""Build small throwaway repositories for exercising the rules tool."""

from __future__ import annotations

import tempfile
import textwrap
from datetime import date
from pathlib import Path
from typing import Self

from scripts.rules.guard import GuardResult, run_guard
from scripts.rules.load import load_registry
from scripts.rules.render import write_outputs
from scripts.rules.resolve import clear_caches

TODAY = date(2026, 6, 1)

REGISTRY = """
schema_version = 1
repo = "example"

[[category]]
id = "layers"
title = "Layers"

[[category]]
id = "quality"
title = "Quality"

[discovery]
guard_test_globs = ["tests/**/test_*boundar*.py"]

[[rule]]
id = "ex.layers.no-sql-in-routes"
category = "layers"
statement = "Routes never issue SQL."
rationale = "docs/guide.md#routes"
scope = ["pkg/*.py"]
tier = "mechanical"
status = "enforced"
autofix = false
[rule.enforcer]
kind = "pytest"
nodes = ["tests/unit/test_boundaries.py::test_routes_have_no_sql"]
[[rule.ci]]
workflow = ".github/workflows/pr.yml"
job = "test"
invocation = "make test"

[[rule]]
id = "ex.layers.services-no-http"
category = "layers"
statement = "Services never build HTTP responses."
rationale = "docs/guide.md"
scope = ["pkg/*.py"]
tier = "mechanical"
status = "enforced"
autofix = false
[rule.enforcer]
kind = "pytest"
nodes = ["tests/unit/test_boundaries.py::TestServices::test_no_http"]
[[rule.ci]]
workflow = ".github/workflows/pr.yml"
job = "test"
invocation = "make test"

[[rule]]
id = "ex.process.registry"
category = "quality"
statement = "The registry is consistent."
rationale = "docs/guide.md"
scope = ["rules/registry.toml"]
tier = "mechanical"
status = "enforced"
autofix = false
[rule.enforcer]
kind = "quality-guard"
name = "rules-registry"
[[rule.ci]]
workflow = ".github/workflows/pr.yml"
job = "quality-guards"
invocation = "run_quality_guards.py"

[[rule]]
id = "ex.quality.format"
category = "quality"
statement = "Code is formatted."
rationale = "docs/guide.md"
scope = ["pkg/*.py"]
tier = "mechanical"
status = "enforced"
autofix = true
[rule.enforcer]
kind = "ruff"
mode = "format"
[[rule.ci]]
workflow = ".github/workflows/pr.yml"
job = "lint"
invocation = "ruff format --check"

[[rule]]
id = "ex.quality.types"
category = "quality"
statement = "The package type-checks."
rationale = "docs/guide.md"
scope = ["pkg/*.py"]
tier = "mechanical"
status = "enforced"
autofix = false
[rule.enforcer]
kind = "mypy"
paths = ["pkg"]
[[rule.ci]]
workflow = ".github/workflows/pr.yml"
job = "typecheck"
invocation = "mypy"

[[rule]]
id = "ex.layers.connectors-never-commit"
category = "layers"
statement = "Connectors never commit."
rationale = "docs/guide.md"
scope = ["pkg/*.py"]
tier = "mechanical"
status = "doc-only"
autofix = false
[rule.enforcer]
kind = "none"
"""

WORKFLOW = """
name: Pull request
on: pull_request
jobs:
  test:
    name: Test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # make test is mentioned in this comment only in some cases
      - name: Run tests
        run: make test
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Format
        run: |
          pip install ruff
          ruff format --check .
  typecheck:
    runs-on: ubuntu-latest
    steps:
      - run: uv run mypy
  quality-guards:
    runs-on: ubuntu-latest
    steps:
      - name: Guards
        run: python scripts/run_quality_guards.py
"""

FILES = {
    "rules/registry.toml": REGISTRY,
    ".github/workflows/pr.yml": WORKFLOW,
    "Makefile": "test:\n\tpython -m pytest tests/unit --disable-pytest-warnings\n",
    "pyproject.toml": '[tool.mypy]\nfiles = ["pkg"]\n',
    "scripts/run_quality_guards.py": ('GUARDS = (("rules-registry", lambda: []),)\n'),
    "tests/unit/test_boundaries.py": textwrap.dedent(
        """
        import pytest


        @pytest.mark.parametrize("path", ["a", "b"])
        def test_routes_have_no_sql(path):
            pass


        class TestServices:
            def test_no_http(self):
                pass
        """
    ),
    "docs/guide.md": "# Guide\n\n## Routes\n",
    "pkg/routes.py": "def route():\n    return 1\n",
    "AGENTS.md": "# Agent Instructions\n\nRead the guide.\n",
}


class Repo:
    """A temporary repository tree. Use as a context manager."""

    def __init__(self, files: dict[str, str] | None = None, *, render: bool = True):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for path, text in {**FILES, **(files or {})}.items():
            self.write(path, text)
        if render:
            self.render()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._tmp.cleanup()

    def write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        clear_caches()

    def read(self, path: str) -> str:
        return (self.root / path).read_text()

    def edit(self, path: str, old: str, new: str) -> None:
        text = self.read(path)
        assert old in text, f"{old!r} not in {path}"
        self.write(path, text.replace(old, new, 1))

    def render(self) -> None:
        clear_caches()
        registry, violations = load_registry(self.root)
        assert registry is not None and not violations, violations
        write_outputs(registry, self.root)

    def guard(self, **kwargs) -> GuardResult:
        kwargs.setdefault("today", TODAY)
        kwargs.setdefault("compare_base", "base_ref" in kwargs)
        return run_guard(self.root, **kwargs)

    def messages(self, **kwargs) -> list[str]:
        return [str(v) for v in self.guard(**kwargs).violations]
