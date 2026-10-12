"""Tests for the rules registry guard, using throwaway repositories."""

from __future__ import annotations

import subprocess
import unittest
from datetime import date

from scripts.rules.baseline import check_baselines
from scripts.rules.load import load_text
from scripts.rules.render import render_agents_block, render_rules_md
from scripts.rules.tests.support import REGISTRY, Repo

RATCHETED_RULE = """
[[rule]]
id = "ex.layers.ratcheted"
category = "layers"
statement = "Ratcheted rule."
rationale = "docs/guide.md"
scope = ["pkg/*.py"]
tier = "mechanical"
status = "ratcheted"
autofix = false
[rule.enforcer]
kind = "pytest"
nodes = ["tests/unit/test_boundaries.py::test_routes_have_no_sql"]
[[rule.ci]]
workflow = ".github/workflows/pr.yml"
job = "test"
invocation = "make test"
[rule.baseline]
file = "rules/baselines/ratcheted.txt"
count = {count}
"""


def with_rule(extra: str) -> dict[str, str]:
    return {"rules/registry.toml": REGISTRY + extra}


class ValidRepositoryTest(unittest.TestCase):
    def test_valid_repository_passes(self) -> None:
        with Repo() as repo:
            self.assertEqual(repo.messages(), [])

    def test_render_is_deterministic(self) -> None:
        with Repo() as repo:
            registry, _ = load_text(repo.read("rules/registry.toml"))
            assert registry is not None
            self.assertEqual(render_rules_md(registry), render_rules_md(registry))
            self.assertEqual(
                render_agents_block(registry), render_agents_block(registry)
            )

    def test_rules_md_lists_gaps(self) -> None:
        with Repo() as repo:
            rules_md = repo.read("docs/generated/rules.md")
            self.assertIn(
                "ex.layers.connectors-never-commit", rules_md.split("## Gaps")[1]
            )
            self.assertIn("```mermaid", rules_md)
            self.assertIn("## Rules", repo.read("AGENTS.md"))


class SchemaTest(unittest.TestCase):
    def assertViolation(self, repo: Repo, fragment: str) -> None:
        messages = repo.messages()
        self.assertTrue(any(fragment in m for m in messages), messages)

    def test_missing_required_field(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml", 'statement = "Routes never issue SQL."\n', ""
            )
            self.assertViolation(repo, "statement must be a non-empty string")

    def test_unknown_enforcer_kind(self) -> None:
        with Repo(render=False) as repo:
            repo.edit("rules/registry.toml", 'kind = "mypy"', 'kind = "flake8"')
            self.assertViolation(repo, "enforcer.kind is 'flake8'")

    def test_bad_status(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml", 'status = "doc-only"', 'status = "optional"'
            )
            self.assertViolation(repo, "status is 'optional'")

    def test_unknown_key(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml",
                "autofix = true",
                'autofix = true\nowner = "someone"',
            )
            self.assertViolation(repo, "unknown key 'owner'")

    def test_duplicate_rule_id(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml",
                'id = "ex.quality.types"',
                'id = "ex.quality.format"',
            )
            self.assertViolation(repo, "duplicate rule id")

    def test_tool_version_mismatch(self) -> None:
        with Repo(render=False) as repo:
            text = repo.read("rules/registry.toml")
            repo.write(
                "rules/registry.toml",
                text.replace('tool_version = "', 'tool_version = "9', 1),
            )
            self.assertViolation(repo, "tool_version is 9")

    def test_scope_glob_must_match(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml",
                'scope = ["rules/registry.toml"]',
                'scope = ["nowhere/*.py"]',
            )
            self.assertViolation(repo, "scope 'nowhere/*.py' matches no files")

    def test_doc_only_rule_cannot_claim_enforcer(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml",
                'status = "enforced"\nautofix = true',
                'status = "doc-only"\nautofix = true',
            )
            self.assertViolation(repo, "doc-only rules have no enforcer")

    def test_enforced_rule_needs_ci(self) -> None:
        extra = """
[[rule]]
id = "ex.layers.local-only"
category = "layers"
statement = "Only checked locally."
rationale = "docs/guide.md"
scope = ["pkg/*.py"]
tier = "mechanical"
status = "enforced"
autofix = false
[rule.enforcer]
kind = "pytest"
nodes = ["tests/unit/test_boundaries.py::test_routes_have_no_sql"]
"""
        with Repo(with_rule(extra), render=False) as repo:
            self.assertViolation(repo, "enforced rules must run in CI")

    def test_ruff_is_never_ratcheted(self) -> None:
        with Repo(render=False) as repo:
            repo.write("rules/baselines/ruff.txt", "pkg/routes.py E501\n")
            repo.edit(
                "rules/registry.toml",
                'kind = "ruff"\nmode = "format"',
                'kind = "ruff"\nmode = "format"\n[rule.baseline]\nfile = "rules/baselines/ruff.txt"\ncount = 1',
            )
            self.assertViolation(repo, "ruff is never ratcheted")

    def test_ratcheted_without_baseline(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml",
                'status = "enforced"\nautofix = false\n[rule.enforcer]\nkind = "mypy"',
                'status = "ratcheted"\nautofix = false\n[rule.enforcer]\nkind = "mypy"',
            )
            self.assertViolation(repo, "ratcheted rules need a baseline")

    def test_baseline_count_must_match_file(self) -> None:
        with Repo(with_rule(RATCHETED_RULE.format(count=3)), render=False) as repo:
            repo.write(
                "rules/baselines/ratcheted.txt",
                "# tolerated\npkg/routes.py\npkg/other.py\n",
            )
            self.assertViolation(
                repo, "baseline count is 3 but rules/baselines/ratcheted.txt lists 2"
            )

    def test_judgment_rules_need_review_enforcer(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml",
                'tier = "mechanical"\nstatus = "enforced"\nautofix = true',
                'tier = "judgment"\nstatus = "enforced"\nautofix = true',
            )
            self.assertViolation(repo, "judgment rules are enforced by review")


class ResolutionTest(unittest.TestCase):
    def assertViolation(self, repo: Repo, fragment: str) -> None:
        messages = repo.messages()
        self.assertTrue(any(fragment in m for m in messages), messages)

    def test_unresolved_pytest_node(self) -> None:
        with Repo() as repo:
            repo.edit(
                "tests/unit/test_boundaries.py",
                "def test_routes_have_no_sql",
                "def test_renamed",
            )
            self.assertViolation(repo, "has no test 'test_routes_have_no_sql'")

    def test_parametrized_node_resolves(self) -> None:
        with Repo() as repo:
            repo.edit(
                "rules/registry.toml",
                'test_boundaries.py::test_routes_have_no_sql"',
                'test_boundaries.py::test_routes_have_no_sql[a]"',
            )
            repo.render()
            self.assertEqual(repo.messages(), [])

    def test_test_outside_make_target_is_not_collected(self) -> None:
        with Repo() as repo:
            repo.edit("Makefile", "tests/unit", "tests/contract")
            self.assertViolation(repo, "is not collected by 'make test'")

    def test_project_must_be_in_matrix(self) -> None:
        workflow = """
jobs:
  test:
    strategy:
      matrix:
        project:
          - projects/alpha
    steps:
      - run: |
          cd ${{ matrix.project }}
          uv run pytest tests/
"""
        extra = """
[[rule]]
id = "ex.layers.beta"
category = "layers"
statement = "Beta rule."
rationale = "docs/guide.md"
scope = ["projects/beta/src/*.py"]
tier = "mechanical"
status = "enforced"
autofix = false
[rule.enforcer]
kind = "pytest"
project = "projects/beta"
nodes = ["tests/test_beta.py::test_beta"]
[[rule.ci]]
workflow = ".github/workflows/matrix.yml"
job = "test"
invocation = "pytest tests/"
"""
        files = {
            ".github/workflows/matrix.yml": workflow,
            "projects/beta/tests/test_beta.py": "def test_beta():\n    pass\n",
            "projects/beta/src/beta.py": "",
            **with_rule(extra),
        }
        with Repo(files) as repo:
            self.assertViolation(
                repo, "project projects/beta is not in the matrix of job 'test'"
            )

    def test_missing_job(self) -> None:
        with Repo() as repo:
            repo.edit("rules/registry.toml", 'job = "typecheck"', 'job = "types"')
            repo.render()
            self.assertViolation(repo, "no job 'types'")

    def test_invocation_only_in_comment_does_not_count(self) -> None:
        with Repo() as repo:
            repo.edit(".github/workflows/pr.yml", "run: make test", "run: echo skipped")
            self.assertViolation(repo, "does not run 'make test'")

    def test_unknown_quality_guard(self) -> None:
        with Repo() as repo:
            repo.edit(
                "rules/registry.toml", 'name = "rules-registry"', 'name = "renamed"'
            )
            repo.render()
            self.assertViolation(repo, "no guard named 'renamed'")

    def test_mypy_path_must_be_configured(self) -> None:
        with Repo() as repo:
            repo.edit(
                "rules/registry.toml", 'paths = ["pkg"]', 'paths = ["pkg", "other"]'
            )
            repo.render()
            self.assertViolation(repo, "['other'] not in [tool.mypy].files")

    def test_ruff_lint_codes_must_be_selected(self) -> None:
        extra = """
[[rule]]
id = "ex.quality.bugbear"
category = "quality"
statement = "No bugbear findings."
rationale = "docs/guide.md"
scope = ["pkg/*.py"]
tier = "mechanical"
status = "advisory"
autofix = false
[rule.enforcer]
kind = "ruff"
mode = "lint"
codes = ["B"]
"""
        with Repo(with_rule(extra)) as repo:
            self.assertViolation(repo, "ruff does not select ['B']")

    def test_proof_files_must_exist(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml",
                'kind = "mypy"\npaths = ["pkg"]',
                'kind = "mypy"\npaths = ["pkg"]\n[rule.proof]\nbad_fixture = "rules/fixtures/bad.py"\n'
                'good_fixture = "rules/fixtures/good.py"\ntest = "tests/unit/test_boundaries.py::test_routes_have_no_sql"',
            )
            self.assertViolation(
                repo, "proof bad_fixture rules/fixtures/bad.py does not exist"
            )


class ProofCiTest(unittest.TestCase):
    PROOF_FILES = {
        "rules/fixtures/bad.py": "import sqlalchemy\n",
        "rules/fixtures/good.py": "x = 1\n",
    }

    def with_proof(self, repo: Repo, rule_marker: str, proof: str) -> None:
        repo.edit(
            "rules/registry.toml", rule_marker, rule_marker + "\n[rule.proof]\n" + proof
        )
        repo.render()

    def test_pytest_rule_proof_runs_in_its_ci_job(self) -> None:
        files = {
            **self.PROOF_FILES,
            "tests/unit/test_proof.py": "def test_rule_proof_routes():\n    pass\n",
        }
        with Repo(files) as repo:
            self.with_proof(
                repo,
                'nodes = ["tests/unit/test_boundaries.py::test_routes_have_no_sql"]',
                'bad_fixture = "rules/fixtures/bad.py"\ngood_fixture = "rules/fixtures/good.py"\n'
                'test = "tests/unit/test_proof.py::test_rule_proof_routes"',
            )
            self.assertEqual(repo.messages(), [])

    def test_proof_outside_the_ci_command_is_rejected(self) -> None:
        files = {
            **self.PROOF_FILES,
            "tests/contract/test_proof.py": "def test_rule_proof_routes():\n    pass\n",
        }
        with Repo(files) as repo:
            self.with_proof(
                repo,
                'nodes = ["tests/unit/test_boundaries.py::test_routes_have_no_sql"]',
                'bad_fixture = "rules/fixtures/bad.py"\ngood_fixture = "rules/fixtures/good.py"\n'
                'test = "tests/contract/test_proof.py::test_rule_proof_routes"',
            )
            messages = "\n".join(repo.messages())
            self.assertIn(
                "proof: tests/contract/test_proof.py is not collected by 'make test'",
                messages,
            )

    def test_non_pytest_rule_proof_must_name_its_job(self) -> None:
        files = {
            **self.PROOF_FILES,
            "tests/unit/test_proof.py": "def test_rule_proof_types():\n    pass\n",
        }
        with Repo(files) as repo:
            self.with_proof(
                repo,
                'paths = ["pkg"]',
                'bad_fixture = "rules/fixtures/bad.py"\ngood_fixture = "rules/fixtures/good.py"\n'
                'test = "tests/unit/test_proof.py::test_rule_proof_types"',
            )
            self.assertIn(
                "the proof test is not tied to a CI job", "\n".join(repo.messages())
            )

    def test_proof_with_named_unittest_job(self) -> None:
        workflow_job = (
            "  tool-tests:\n    steps:\n"
            "      - run: python -m unittest discover -s tools/tests -t .\n"
        )
        files = {
            **self.PROOF_FILES,
            "tools/tests/test_proof.py": "class TestProof:\n    def test_rule_proof_types(self):\n        pass\n",
        }
        with Repo(files, render=False) as repo:
            repo.write(
                ".github/workflows/pr.yml",
                repo.read(".github/workflows/pr.yml") + workflow_job,
            )
            repo.edit(
                "rules/registry.toml",
                "[discovery]\n",
                '[discovery]\nignore_jobs = [{ job = "tool-tests", reason = "runs tool tests" }]\n',
            )
            proof = (
                'bad_fixture = "rules/fixtures/bad.py"\ngood_fixture = "rules/fixtures/good.py"\n'
                'test = "tools/tests/test_proof.py::TestProof::test_rule_proof_types"\n'
                'workflow = ".github/workflows/pr.yml"\njob = "tool-tests"\n'
                'invocation = "unittest discover -s tools/tests"'
            )
            self.with_proof(repo, 'paths = ["pkg"]', proof)
            self.assertEqual(repo.messages(), [])

            repo.edit("rules/registry.toml", 'job = "tool-tests"\n', "")
            repo.render()
            self.assertIn(
                "proof names its CI job only partly", "\n".join(repo.messages())
            )


class HiddenRuleTest(unittest.TestCase):
    def assertViolation(self, repo: Repo, fragment: str) -> None:
        messages = repo.messages()
        self.assertTrue(any(fragment in m for m in messages), messages)

    def test_unregistered_quality_guard(self) -> None:
        with Repo() as repo:
            repo.write(
                "scripts/run_quality_guards.py",
                'GUARDS = (("rules-registry", lambda: []), ("secret-guard", lambda: []))\n',
            )
            self.assertViolation(repo, "quality guard 'secret-guard'")

    def test_unregistered_guard_test(self) -> None:
        with Repo() as repo:
            text = repo.read("tests/unit/test_boundaries.py")
            repo.write(
                "tests/unit/test_boundaries.py",
                text + "\n\ndef test_new_boundary():\n    pass\n",
            )
            self.assertViolation(
                repo, "test_boundaries.py::test_new_boundary is not referenced"
            )

    def test_unregistered_mypy_file(self) -> None:
        with Repo() as repo:
            repo.write("pyproject.toml", '[tool.mypy]\nfiles = ["pkg", "scripts"]\n')
            self.assertViolation(repo, "mypy checks 'scripts'")

    def test_unregistered_ruff_ignore(self) -> None:
        with Repo() as repo:
            repo.write(
                "pyproject.toml",
                '[tool.mypy]\nfiles = ["pkg"]\n\n[tool.ruff.lint.per-file-ignores]\n"pkg/*.py" = ["E501"]\n',
            )
            self.assertViolation(repo, "ruff per-file-ignores 'pkg/*.py' has no rule")

    def test_unregistered_ci_job(self) -> None:
        with Repo() as repo:
            text = repo.read(".github/workflows/pr.yml")
            repo.write(
                ".github/workflows/pr.yml",
                text + "  deploy:\n    steps:\n      - run: ./deploy.sh\n",
            )
            self.assertViolation(repo, "CI job 'deploy'")

    def test_ignored_ci_job_with_reason_passes(self) -> None:
        with Repo() as repo:
            text = repo.read(".github/workflows/pr.yml")
            repo.write(
                ".github/workflows/pr.yml",
                text + "  deploy:\n    steps:\n      - run: ./deploy.sh\n",
            )
            repo.edit(
                "rules/registry.toml",
                "[discovery]\n",
                '[discovery]\nignore_jobs = [{ job = "deploy", reason = "deploys, enforces nothing" }]\n',
            )
            repo.render()
            self.assertEqual(repo.messages(), [])


class RenderFreshnessTest(unittest.TestCase):
    def test_stale_rules_md(self) -> None:
        with Repo() as repo:
            repo.write(
                "docs/generated/rules.md",
                repo.read("docs/generated/rules.md") + "edited\n",
            )
            self.assertIn(
                "[registry] render: docs/generated/rules.md is stale",
                "\n".join(repo.messages()),
            )

    def test_missing_agents_markers(self) -> None:
        with Repo() as repo:
            repo.write("AGENTS.md", "# Agent Instructions\n")
            self.assertIn(
                "AGENTS.md has no generated rules block", "\n".join(repo.messages())
            )

    def test_stale_agents_block(self) -> None:
        with Repo() as repo:
            repo.edit("AGENTS.md", "Routes never issue SQL.", "Routes may issue SQL.")
            self.assertIn(
                "the rules block in AGENTS.md is stale", "\n".join(repo.messages())
            )

    def test_render_keeps_surrounding_agents_text(self) -> None:
        with Repo() as repo:
            agents = repo.read("AGENTS.md")
            self.assertTrue(
                agents.startswith("# Agent Instructions\n\nRead the guide.\n")
            )
            repo.render()
            self.assertEqual(repo.read("AGENTS.md"), agents)


class ExpiryTest(unittest.TestCase):
    def test_expired_review_by(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml",
                'statement = "Code is formatted."',
                'statement = "Code is formatted."\nreview_by = 2026-01-01',
            )
            repo.render()
            messages = "\n".join(repo.messages())
            self.assertIn("review_by 2026-01-01 has passed", messages)

    def test_expired_exception(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml",
                'kind = "mypy"\npaths = ["pkg"]',
                'kind = "mypy"\npaths = ["pkg"]\n[[rule.exception]]\npath = "pkg/routes.py"\n'
                'reason = "migrating"\nexpires = 2026-05-01',
            )
            repo.render()
            self.assertIn(
                "exception for pkg/routes.py expired on 2026-05-01",
                "\n".join(repo.messages()),
            )
            self.assertEqual(repo.messages(today=date(2026, 4, 1)), [])

    def test_exception_is_listed_in_rules_md(self) -> None:
        with Repo(render=False) as repo:
            repo.edit(
                "rules/registry.toml",
                'kind = "mypy"\npaths = ["pkg"]',
                'kind = "mypy"\npaths = ["pkg"]\n[[rule.exception]]\npath = "pkg/routes.py"\n'
                'reason = "migrating"\nexpires = 2026-12-01',
            )
            repo.render()
            self.assertIn(
                "exception for `pkg/routes.py` until 2026-12-01",
                repo.read("docs/generated/rules.md"),
            )


class BaselineTest(unittest.TestCase):
    def registry(self, extra: str):
        registry, violations = load_text(REGISTRY + extra)
        assert registry is not None and not violations, violations
        return registry

    def test_baseline_may_shrink(self) -> None:
        base = self.registry(RATCHETED_RULE.format(count=3))
        current = self.registry(RATCHETED_RULE.format(count=2))
        self.assertEqual(check_baselines(current, base)[0], [])

    def test_baseline_may_not_grow(self) -> None:
        base = self.registry(RATCHETED_RULE.format(count=2))
        current = self.registry(RATCHETED_RULE.format(count=3))
        violations = check_baselines(current, base)[0]
        self.assertIn("baseline grew from 2 to 3", str(violations[0]))

    def test_downgrade_needs_reason(self) -> None:
        base = self.registry("")
        weakened = REGISTRY.replace(
            'status = "enforced"\nautofix = true\n[rule.enforcer]\nkind = "ruff"\nmode = "format"\n[[rule.ci]]\n'
            'workflow = ".github/workflows/pr.yml"\njob = "lint"\ninvocation = "ruff format --check"',
            'status = "advisory"\nautofix = true\n[rule.enforcer]\nkind = "ruff"\nmode = "format"',
        )
        current, _ = load_text(weakened)
        assert current is not None
        violations = check_baselines(current, base)[0]
        self.assertIn("status weakened from enforced to advisory", str(violations[0]))

        with_reason, _ = load_text(
            weakened.replace(
                'mode = "format"',
                'mode = "format"\n[rule.downgrade]\nreason = "flaky"',
                1,
            )
        )
        assert with_reason is not None
        self.assertEqual(check_baselines(with_reason, base)[0], [])

    def test_compares_against_git_base_ref(self) -> None:
        with Repo(with_rule(RATCHETED_RULE.format(count=1)), render=False) as repo:
            repo.write("rules/baselines/ratcheted.txt", "pkg/routes.py\n")
            repo.render()
            git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]
            subprocess.run(["git", "init", "-q"], cwd=repo.root, check=True)
            subprocess.run([*git, "add", "-A"], cwd=repo.root, check=True)
            subprocess.run([*git, "commit", "-qm", "base"], cwd=repo.root, check=True)
            repo.edit("rules/registry.toml", "count = 1", "count = 2")
            repo.write("rules/baselines/ratcheted.txt", "pkg/routes.py\npkg/other.py\n")
            repo.render()
            self.assertIn(
                "baseline grew from 1 to 2", "\n".join(repo.messages(base_ref="HEAD"))
            )


if __name__ == "__main__":
    unittest.main()
