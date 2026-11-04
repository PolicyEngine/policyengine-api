"""Tests that an Import Linter rule matches its contract and its baseline."""

from __future__ import annotations

import textwrap
import unittest

from scripts.rules.model import Baseline, Enforcer, Kind, Rule, Status, Tier
from scripts.rules.resolve import resolve_enforcer
from scripts.rules.tests.support import Repo

BASELINE_FILE = "rules/baselines/import-linter-pkg-pure.txt"
CONFIG = textwrap.dedent(
    """
    [tool.importlinter]
    root_package = "pkg"

    [[tool.importlinter.contracts]]
    id = "pkg-pure"
    name = "Pure modules import no database code"
    type = "forbidden"
    source_modules = ["pkg.pure"]
    forbidden_modules = ["sqlalchemy"]
    ignore_imports = [
        "pkg.models -> sqlalchemy",
        "pkg.pure.legacy -> sqlalchemy",
    ]
    unmatched_ignore_imports_alerting = "error"

    [[tool.importlinter.contracts]]
    id = "pkg-layers"
    name = "Layers"
    type = "layers"
    layers = ["pkg.routes", "pkg.services"]
    """
)


def import_linter_rule(
    contract: str,
    *,
    baseline: Baseline | None = None,
    allowed: object = None,
) -> Rule:
    fields: dict[str, object] = {"config": "pyproject.toml", "contract": contract}
    if allowed is not None:
        fields["allowed_ignore_imports"] = allowed
    return Rule(
        id="ex.r",
        category="checks",
        statement="A statement.",
        rationale="docs/guide.md",
        scope=("pkg/*.py",),
        tier=Tier.MECHANICAL,
        status=Status.RATCHETED if baseline else Status.ENFORCED,
        autofix=False,
        enforcer=Enforcer(Kind.IMPORT_LINTER, fields),
        baseline=baseline,
    )


class TestImportLinterEnforcer(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo({"pyproject.toml": CONFIG}, render=False)
        self.addCleanup(self.repo.__exit__)
        self.repo.write(
            BASELINE_FILE,
            "# Tolerated existing violations. This list may only shrink.\n"
            "pkg.pure.legacy -> sqlalchemy\n",
        )

    def messages(self, rule: Rule) -> list[str]:
        return [str(violation) for violation in resolve_enforcer(rule, self.repo.root)]

    def test_a_contract_matching_its_baseline_and_allowed_imports_passes(self) -> None:
        rule = import_linter_rule(
            "pkg-pure",
            baseline=Baseline(BASELINE_FILE, 1),
            allowed=["pkg.models -> sqlalchemy"],
        )

        self.assertEqual(self.messages(rule), [])

    def test_a_contract_without_exceptions_passes_without_a_baseline(self) -> None:
        self.assertEqual(self.messages(import_linter_rule("pkg-layers")), [])

    def test_the_contract_must_exist(self) -> None:
        self.assertEqual(
            self.messages(import_linter_rule("pkg-missing")),
            [
                "[ex.r] enforcer: pyproject.toml has no Import Linter contract with "
                "id 'pkg-missing'. Fix: add the contract to [tool.importlinter] or "
                "fix enforcer.contract."
            ],
        )

    def test_the_config_must_hold_an_import_linter_section(self) -> None:
        self.repo.write("pyproject.toml", '[tool.mypy]\nfiles = ["pkg"]\n')

        self.assertEqual(
            self.messages(import_linter_rule("pkg-layers")),
            [
                "[ex.r] enforcer: pyproject.toml has no Import Linter contract with "
                "id 'pkg-layers'. Fix: add the contract to [tool.importlinter] or "
                "fix enforcer.contract."
            ],
        )

    def test_an_ignored_import_missing_from_the_baseline_fails(self) -> None:
        rule = import_linter_rule("pkg-pure", allowed=["pkg.models -> sqlalchemy"])

        self.assertEqual(
            self.messages(rule),
            [
                "[ex.r] enforcer: contract 'pkg-pure' ignores imports that neither "
                "the rule's baseline nor enforcer.allowed_ignore_imports lists: "
                "pkg.pure.legacy -> sqlalchemy. Fix: fix the import instead, or "
                "list it in the rule's baseline file under rules/baselines/."
            ],
        )

    def test_a_baseline_entry_the_contract_does_not_ignore_fails(self) -> None:
        self.repo.write(
            BASELINE_FILE,
            "pkg.pure.legacy -> sqlalchemy\npkg.pure.fixed -> sqlalchemy\n",
        )
        rule = import_linter_rule(
            "pkg-pure",
            baseline=Baseline(BASELINE_FILE, 2),
            allowed=["pkg.models -> sqlalchemy"],
        )

        self.assertEqual(
            self.messages(rule),
            [
                "[ex.r] enforcer: the rule's baseline and "
                "enforcer.allowed_ignore_imports list imports that contract "
                "'pkg-pure' does not ignore: pkg.pure.fixed -> sqlalchemy. "
                "Fix: remove them from the baseline, or add them to the "
                "contract's ignore_imports."
            ],
        )

    def test_ignored_imports_need_unmatched_alerting_set_to_error(self) -> None:
        self.repo.edit(
            "pyproject.toml", 'unmatched_ignore_imports_alerting = "error"\n', ""
        )
        rule = import_linter_rule(
            "pkg-pure",
            baseline=Baseline(BASELINE_FILE, 1),
            allowed=["pkg.models -> sqlalchemy"],
        )

        self.assertEqual(
            self.messages(rule),
            [
                "[ex.r] enforcer: contract 'pkg-pure' has ignore_imports but does "
                'not set unmatched_ignore_imports_alerting = "error", so an '
                "exception that no longer matches would pass. Fix: set it on the "
                "contract."
            ],
        )

    def test_allowed_ignore_imports_must_be_a_list_of_strings(self) -> None:
        rule = import_linter_rule(
            "pkg-pure",
            baseline=Baseline(BASELINE_FILE, 1),
            allowed="pkg.models -> sqlalchemy",
        )

        self.assertEqual(
            self.messages(rule),
            [
                "[ex.r] enforcer: enforcer.allowed_ignore_imports must be a list "
                "of imports written as Import Linter writes them, such as "
                "'pkg.models -> sqlalchemy'. Fix: make it a list of strings."
            ],
        )


if __name__ == "__main__":
    unittest.main()
