"""Tests for the ci-scripts guard: workflow logic lives in tested shell scripts."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.rules.ci_scripts import (
    Findings,
    compare,
    multiline_runs,
    shellcheck_failures,
    untested_scripts,
)
from scripts.rules.load import load_text
from scripts.rules.model import CiScripts
from scripts.rules.workflows import chains_commands, code_lines, parse_jobs

FIXTURES = Path(__file__).parent / "fixtures" / "ci_scripts"
CONFIG = CiScripts(
    workflows=".github/workflows/*.yml",
    scripts_dir=".github/scripts",
    test_globs=("tests/**/test_*.py",),
    multiline_baseline="rules/baselines/ci-multiline-run.txt",
    untested_baseline="rules/baselines/ci-untested-scripts.txt",
    shellcheck_baseline="rules/baselines/ci-shellcheck.txt",
)


def require_shellcheck(test: unittest.TestCase) -> None:
    if shutil.which("shellcheck") is None:
        if os.environ.get("GITHUB_ACTIONS"):
            test.fail("shellcheck must be installed in CI")
        test.skipTest("shellcheck is not installed")


class TestCiScriptsProof(unittest.TestCase):
    """Proofs that each ci-scripts check rejects a bad example and accepts a good one."""

    def test_rule_proof_multiline_run(self) -> None:
        self.assertEqual(
            multiline_runs(CONFIG, FIXTURES / "multiline_bad"),
            {
                ".github/workflows/ci.yml :: build :: Build",
                ".github/workflows/ci.yml :: build :: Folded test command",
                ".github/workflows/ci.yml :: build :: Chained",
            },
        )
        self.assertEqual(multiline_runs(CONFIG, FIXTURES / "multiline_good"), set())

    def test_rule_proof_untested_script(self) -> None:
        self.assertEqual(
            untested_scripts(CONFIG, FIXTURES / "untested_bad"),
            {".github/scripts/deploy.sh"},
        )
        self.assertEqual(untested_scripts(CONFIG, FIXTURES / "untested_good"), set())

    def test_rule_proof_shellcheck(self) -> None:
        require_shellcheck(self)
        for name, expected in (("bad_script.sh", True), ("good_script.sh", False)):
            with tempfile.TemporaryDirectory() as tmp:
                scripts = Path(tmp) / ".github" / "scripts"
                scripts.mkdir(parents=True)
                shutil.copy(FIXTURES / "shellcheck" / name, scripts / name)
                failures = shellcheck_failures(CONFIG, Path(tmp))
                self.assertEqual(bool(failures), expected, name)


class CodeLinesTest(unittest.TestCase):
    def test_every_line_counts(self) -> None:
        self.assertEqual(code_lines("make deps\nmake build"), 2)

    def test_backslash_continuation_lines_count(self) -> None:
        self.assertEqual(code_lines("docker build \\\n  --tag x \\\n  ."), 3)

    def test_blank_lines_do_not_count(self) -> None:
        self.assertEqual(code_lines("\nmake build\n\n"), 1)

    def test_folded_block_counts_each_line(self) -> None:
        text = "jobs:\n  a:\n    steps:\n      - run: >-\n          pytest a\n          b\n"
        jobs, _ = parse_jobs(text)
        block = jobs["a"].run_blocks[0]
        self.assertEqual(block.code_lines, 2)
        self.assertFalse(block.single_line)

    def test_chained_commands_are_not_one_line(self) -> None:
        for text in ("a && b", "a || b", "a; b", 'cd "$dir" && make'):
            self.assertTrue(chains_commands(text), text)

    def test_operators_in_quotes_and_expressions_are_ignored(self) -> None:
        for text in (
            'echo "a; b"',
            "echo 'a && b'",
            "echo ${{ a && b || c }}",
            "echo \\; done",
            "pytest -q | tee log",
        ):
            self.assertFalse(chains_commands(text), text)

    def test_comment_lines_are_stripped_by_the_reader(self) -> None:
        text = (
            "jobs:\n  a:\n    steps:\n      - name: One\n        run: |\n"
            "          # explain\n          make build\n"
        )
        jobs, _ = parse_jobs(text)
        self.assertEqual(jobs["a"].run_blocks[0].code_lines, 1)

    def test_steps_are_labelled_by_name_or_position(self) -> None:
        text = (
            "jobs:\n  a:\n    steps:\n    - uses: actions/checkout@v4\n"
            "    - run: |\n        one\n        two\n      name: Named after\n"
            "    - run: echo three\n"
        )
        jobs, _ = parse_jobs(text)
        steps = [(block.step, block.code_lines) for block in jobs["a"].run_blocks]
        self.assertEqual(steps, [("Named after", 2), ("step 3", 1)])


REGISTRY = """
schema_version = 1
repo = "example"

[[category]]
id = "ci"
title = "CI"

[ci_scripts]
workflows = ".github/workflows/*.yml"
scripts_dir = ".github/scripts"
test_globs = ["tests/**/test_*.py"]
multiline_baseline = "rules/baselines/ci-multiline-run.txt"
untested_baseline = "rules/baselines/ci-untested-scripts.txt"
shellcheck_baseline = "rules/baselines/ci-shellcheck.txt"

[[rule]]
id = "ex.ci.multiline"
category = "ci"
statement = "One line per run block."
rationale = "README.md"
scope = ["README.md"]
tier = "mechanical"
status = "ratcheted"
autofix = false
[rule.enforcer]
kind = "quality-guard"
name = "ci-scripts"
[[rule.ci]]
workflow = ".github/workflows/pr.yml"
job = "guards"
invocation = "run_quality_guards.py"
[rule.baseline]
file = "rules/baselines/ci-multiline-run.txt"
count = 1
"""


class CompareTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        baselines = self.root / "rules" / "baselines"
        baselines.mkdir(parents=True)
        (baselines / "ci-multiline-run.txt").write_text(
            "# tolerated\nold :: job :: step\n"
        )
        registry, violations = load_text(REGISTRY)
        assert registry is not None and not violations, violations
        self.registry = registry

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def messages(self, found: set[str]) -> list[str]:
        findings = Findings(multiline=found, untested=set(), shellcheck=set())
        return [str(v) for v in compare(self.registry, findings, self.root)]

    def test_baselined_finding_passes(self) -> None:
        self.assertEqual(self.messages({"old :: job :: step"}), [])

    def test_new_finding_fails_with_its_rule_id(self) -> None:
        messages = self.messages({"old :: job :: step", "new :: job :: step"})
        self.assertEqual(len(messages), 1)
        self.assertIn(
            "[ex.ci.multiline] ci-scripts: multi-line run: block new :: job :: step",
            messages[0],
        )

    def test_fixed_finding_must_leave_the_baseline(self) -> None:
        messages = self.messages(set())
        self.assertIn(
            "baseline entry no longer applies: old :: job :: step", messages[0]
        )


if __name__ == "__main__":
    unittest.main()
