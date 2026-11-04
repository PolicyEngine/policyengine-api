"""Tests for the suppressions guard: every noqa and type: ignore is explained."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.rules.suppressions import (
    REPO_ROOT,
    RULE_ID,
    Suppression,
    comment_problems,
    compare,
    run_check,
    unexplained_suppressions,
)

FIXTURES = REPO_ROOT / "rules" / "fixtures" / RULE_ID
BASELINE_FILE = "rules/baselines/suppressions.txt"
NO_CODE = ("a code",)
NO_REASON = ("a reason",)
NEITHER = ("a code", "a reason")


def _suppression(path: str, line: int, source_line: str) -> Suppression:
    comment = source_line[source_line.index("#") :]
    return Suppression(path, line, comment, source_line, comment_problems(comment))


def _registry_with_rule(baseline_block: str) -> str:
    """Return a registry holding only the suppressions rule, with ``baseline_block``."""
    return textwrap.dedent(
        f"""
        schema_version = 1
        repo = "example"

        [[category]]
        id = "quality"
        title = "Quality"

        [[rule]]
        id = "{RULE_ID}"
        category = "quality"
        statement = "Suppressions are explained."
        rationale = "docs/guide.md"
        scope = ["**/*.py"]
        tier = "mechanical"
        status = "ratcheted"
        autofix = false
        [rule.enforcer]
        kind = "quality-guard"
        name = "suppressions"
        [[rule.ci]]
        workflow = ".github/workflows/pr.yml"
        job = "quality-guards"
        invocation = "run_quality_guards.py"
        {baseline_block}
        """
    )


class TestSuppressionsProof(unittest.TestCase):
    """Proof: the rejected fixture's suppressions fail, the accepted ones pass."""

    def test_rule_proof_suppressions_explained(self) -> None:
        rejected = unexplained_suppressions(
            "rejected.py", (FIXTURES / "rejected_module.txt").read_text()
        )
        self.assertEqual(
            [(found.line, found.missing) for found in rejected],
            [
                (6, NO_REASON),
                (7, NEITHER),
                (8, NEITHER),
                (9, NO_REASON),
                (10, NO_REASON),
                (11, NEITHER),
                (12, NO_REASON),
                (13, NO_CODE),
            ],
        )
        accepted = unexplained_suppressions(
            "accepted.py", (FIXTURES / "accepted_module.txt").read_text()
        )
        self.assertEqual(accepted, [])


class TestCommentProblems(unittest.TestCase):
    """What a comment lacks, if it is a suppression."""

    def test_each_comment_form(self) -> None:
        cases = {
            "# noqa": NEITHER,
            "# NOQA": NEITHER,
            "# noqa: E501": NO_REASON,
            "# noqa:E501,W291": NO_REASON,
            "# noqa: E501 the URL is long": NO_REASON,
            "# noqa: E501  # the URL is long": (),
            "# noqa:E501, W291  # generated": (),
            "# ruff: noqa": NEITHER,
            "# ruff: noqa: E402": NO_REASON,
            "# ruff: noqa: E402  # path setup first": (),
            "# flake8: noqa": NEITHER,
            "# type: ignore": NEITHER,
            "# type: ignore[]": NEITHER,
            "# type: ignore[arg-type]": NO_REASON,
            "# type:ignore[arg-type, misc]  # the stub is wrong": (),
            "# type: ignore[arg-type]  # noqa: E501": NO_REASON,
            "# type: ignore[arg-type]  # noqa: E501  # a long stub name": (),
            "# a reason first  # noqa: E501": (),
            "# the word noqa in prose": (),
            "# type annotations are ignored here": (),
            "# see #4182": (),
        }
        for comment, missing in cases.items():
            with self.subTest(comment=comment):
                self.assertEqual(comment_problems(comment), missing)

    def test_spacing_and_case_match_ruff_and_mypy(self) -> None:
        cases = {
            # mypy reads the codes after a space or tab before the bracket.
            "# type: ignore [assignment]  # the stub is wrong": (),
            "# type:\tignore\t[assignment]  # the stub is wrong": (),
            "# type: ignore [assignment]": NO_REASON,
            # ruff reads only the word noqa case-insensitively.
            "# ruff: NOQA: F401": NO_REASON,
            "# Ruff: noqa: F401": (),
            "# FLAKE8: NOQA": (),
            # mypy and Python read type: ignore in lowercase only.
            "# TYPE: IGNORE": (),
        }
        for comment, missing in cases.items():
            with self.subTest(comment=comment):
                self.assertEqual(comment_problems(comment), missing)

    def test_other_tools_directives_are_not_reasons(self) -> None:
        for comment in (
            "# noqa: E501  # fmt: skip",
            "# noqa: E501  # pragma: no cover",
            "# type: ignore[misc]  # pyright: ignore",
            "# noqa: S101  # nosec",
            "# noqa: I001  # isort: skip",
            "# type: ignore[misc]  # mypy: disable-error-code=misc",
        ):
            with self.subTest(comment=comment):
                self.assertEqual(comment_problems(comment), NO_REASON)
        self.assertEqual(comment_problems("# noqa: E501  # fmt: skip  # generated"), ())

    def test_ruff_range_suppressions_need_a_code_and_a_reason(self) -> None:
        cases = {
            "# ruff: disable[T201]": NO_REASON,
            "# ruff: disable[T201]  # the command prints its report": (),
            "# ruff: disable[]  # prints": NO_CODE,
            "# ruff: disable": NEITHER,
            "# ruff: enable[T201]": (),
        }
        for comment, missing in cases.items():
            with self.subTest(comment=comment):
                self.assertEqual(comment_problems(comment), missing)

    def test_a_type_ignore_whose_brackets_hold_no_code_names_none(self) -> None:
        for comment in (
            "# type: ignore[,]  # the stub is wrong",
            "# type: ignore[ , ]  # the stub is wrong",
        ):
            with self.subTest(comment=comment):
                self.assertEqual(comment_problems(comment), NO_CODE)
        self.assertEqual(
            comment_problems("# type: ignore[arg-type, misc]  # the stub is wrong"),
            (),
        )

    def test_a_reason_may_start_with_a_tool_name_and_a_colon(self) -> None:
        for comment in (
            "# noqa: F401  # mypy: the plugin cannot see it",
            "# type: ignore[arg-type]  # Type: the stub says str but bytes work",
            "# type: ignore[arg-type]  # type: the stub says str but bytes work",
            "# noqa: S603  # Ruff: false positive, the arguments are constants",
            "# noqa: E501  # fmt: the formatter would split this URL",
            "# noqa: E501  # isort: keep this order, the import has side effects",
            "# noqa: E501  # pragma: the URL can't be split",
        ):
            with self.subTest(comment=comment):
                self.assertEqual(comment_problems(comment), ())

    def test_more_tools_directives_are_not_reasons(self) -> None:
        for comment in (
            "# noqa: E501  # ty: ignore[unresolved-import]",
            "# noqa: E501  # pyrefly: ignore",
            "# noqa: E501  # pyre-ignore[16]",
            "# noqa: E501  # pyre-fixme[16]",
            "# noqa: E501  # pytype: disable=attribute-error",
            "# noqa: E501  # yapf: disable",
            "# noqa: E501  # nosemgrep",
            "# noqa: E501  # NOSONAR",
            "# noqa: E501  # noinspection PyUnresolvedReferences",
            "# noqa: E501  # codespell:ignore",
            "# noqa: E501  # pragma no cover",
            "# noqa: E501  # ruff: isort: skip",
            "# noqa: E501  # ruff: enable[E501]",
            "# noqa: E501  # mypy: disable-error-code=misc, warn-unreachable",
            "# noqa: E501  # pylint: disable=line-too-long",
        ):
            with self.subTest(comment=comment):
                self.assertEqual(comment_problems(comment), NO_REASON)

    def test_entries_use_the_lines_tokenize_counts(self) -> None:
        source = (
            "a = 1\n\x0c\nimport os  # noqa: F401\n"
            's = "\u2028"\nimport sys  # noqa: F401\n'
        )
        found = unexplained_suppressions("pkg/m.py", source)
        self.assertEqual(
            [(suppression.line, suppression.entry) for suppression in found],
            [
                (3, "pkg/m.py :: import os  # noqa: F401"),
                (5, "pkg/m.py :: import sys  # noqa: F401"),
            ],
        )

    def test_a_byte_order_mark_is_not_part_of_the_entry(self) -> None:
        (found,) = unexplained_suppressions(
            "pkg/m.py", "\ufeffimport os  # noqa: F401\n"
        )
        self.assertEqual(found.entry, "pkg/m.py :: import os  # noqa: F401")

    def test_strings_are_not_comments(self) -> None:
        source = 'TEXT = "# noqa"\nOTHER = """\n# type: ignore\n"""\n'
        self.assertEqual(unexplained_suppressions("module.py", source), [])

    def test_the_entry_is_the_path_and_the_source_line(self) -> None:
        (found,) = unexplained_suppressions(
            "pkg/module.py", "import os\n    import sys  # noqa: F401\n"
        )
        self.assertEqual(found.line, 2)
        self.assertEqual(found.entry, "pkg/module.py :: import sys  # noqa: F401")

    def test_an_untokenizable_module_is_reported(self) -> None:
        with self.assertRaises(SyntaxError):
            unexplained_suppressions("module.py", 'TEXT = """never closed\n')


class TestBaseline(unittest.TestCase):
    """The baseline tolerates listed suppressions and may only shrink."""

    def test_unlisted_suppression_fails(self) -> None:
        found = [
            _suppression("pkg/a.py", 3, "import os  # noqa: F401"),
            _suppression("pkg/b.py", 9, "x = f()  # type: ignore[misc]"),
        ]
        violations = compare(
            found, ["pkg/a.py :: import os  # noqa: F401"], BASELINE_FILE
        )
        self.assertEqual(
            [str(violation) for violation in violations],
            [
                f"[{RULE_ID}] suppressions: pkg/b.py:9: `# type: ignore[misc]` "
                "gives no reason. Fix: name what it suppresses and say why, as "
                "`# noqa: CODE  # reason` or `# type: ignore[code]  # reason`, "
                "once a code change or a setting can't remove the finding "
                "(api.process.agents-suppress-as-last-resort; "
                "docs/engineering/skills/rules-registry.md#inline-suppressions)."
            ],
        )

    def test_a_suppression_with_neither_names_both(self) -> None:
        (violation,) = compare(
            [_suppression("pkg/a.py", 1, "import os  # noqa")], [], BASELINE_FILE
        )
        self.assertEqual(
            violation.message, "pkg/a.py:1: `# noqa` names no code and gives no reason"
        )

    def test_each_listed_occurrence_tolerates_one_suppression(self) -> None:
        line = "from x import (  # noqa: E402"
        found = [
            _suppression("pkg/a.py", 3, line),
            _suppression("pkg/a.py", 9, line),
        ]
        entry = f"pkg/a.py :: {line}"
        self.assertEqual(compare(found, [entry, entry], BASELINE_FILE), [])
        self.assertEqual(
            [violation.message for violation in compare(found, [entry], BASELINE_FILE)],
            ["pkg/a.py:9: `# noqa: E402` gives no reason"],
        )

    def test_listed_entry_no_longer_found_fails(self) -> None:
        violations = compare([], ["pkg/a.py :: import os  # noqa: F401"], BASELINE_FILE)
        self.assertEqual(
            [str(violation) for violation in violations],
            [
                f"[{RULE_ID}] suppressions: baseline entry no longer applies: "
                "pkg/a.py :: import os  # noqa: F401. Fix: remove it from "
                f"{BASELINE_FILE} and lower the rule's baseline count."
            ],
        )


class TestRunCheck(unittest.TestCase):
    """The guard scans every Python file under the root against the baseline."""

    def test_scans_files_and_reads_the_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "rules" / "baselines").mkdir(parents=True)
            (root / "rules" / "baselines" / "suppressions.txt").write_text(
                "# Tolerated.\npkg/old.py :: import os  # noqa: F401\n"
            )
            (root / "rules" / "registry.toml").write_text(
                _registry_with_rule(
                    f'[rule.baseline]\nfile = "{BASELINE_FILE}"\ncount = 1\n'
                )
            )
            (root / "pkg").mkdir()
            (root / "pkg" / "old.py").write_text("import os  # noqa: F401\n")
            (root / "pkg" / "new.py").write_text("import sys  # noqa: F401\n")
            (root / "pkg" / "broken.py").write_text('TEXT = """never closed\n')
            (root / "pkg" / "stub.pyi").write_text("import os  # noqa: F401\n")
            messages = [violation.message for violation in run_check(root)]
        self.assertEqual(
            messages,
            [
                "pkg/broken.py doesn't tokenize, so its suppressions can't be checked",
                "pkg/new.py:1: `# noqa: F401` gives no reason",
                "pkg/stub.pyi:1: `# noqa: F401` gives no reason",
            ],
        )

    def test_missing_rule_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "rules").mkdir()
            (root / "rules" / "registry.toml").write_text(
                'schema_version = 1\nrepo = "example"\n'
            )
            messages = [violation.message for violation in run_check(root)]
        self.assertEqual(messages, [f"rules/registry.toml has no rule {RULE_ID}"])


class TestRepository(unittest.TestCase):
    """The repository has no unexplained suppression outside the baseline."""

    def test_repository_has_no_violations(self) -> None:
        self.assertEqual([str(violation) for violation in run_check(REPO_ROOT)], [])


if __name__ == "__main__":
    unittest.main()
