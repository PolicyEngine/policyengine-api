"""Tests that an Import Linter rule matches its contract and its baseline."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import textwrap
import tomllib
import unittest

from scripts.rules.model import Baseline, CiRef, Enforcer, Kind, Rule, Status, Tier
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


def fingerprint(config: str, contract_id: str) -> str:
    """Return the SHA-256 of a contract's definition, as the rules guard does.

    It covers the top-level [tool.importlinter] settings and every field of the
    contract except ignore_imports, serialised as JSON with sorted keys.
    """
    settings = tomllib.loads(config)["tool"]["importlinter"]
    contract = next(
        table for table in settings["contracts"] if table["id"] == contract_id
    )
    definition = {
        "settings": {
            key: value for key, value in settings.items() if key != "contracts"
        },
        "contract": {
            key: value for key, value in contract.items() if key != "ignore_imports"
        },
    }
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def import_linter_rule(
    contract: str,
    *,
    baseline: Baseline | None = None,
    allowed: object = None,
    sha256: str | None = None,
) -> Rule:
    fields: dict[str, object] = {"config": "pyproject.toml", "contract": contract}
    if allowed is not None:
        fields["allowed_ignore_imports"] = allowed
    if sha256 is None and contract not in ("", "pkg-missing"):
        sha256 = fingerprint(CONFIG, contract)
    if sha256 is not None:
        fields["contract_sha256"] = sha256
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
            sha256=fingerprint(self.repo.read("pyproject.toml"), "pkg-pure"),
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

    def test_a_tolerated_exception_must_name_one_import(self) -> None:
        self.repo.edit(
            "pyproject.toml",
            '"pkg.pure.legacy -> sqlalchemy",',
            '"pkg.pure.* -> sqlalchemy",',
        )
        self.repo.write(BASELINE_FILE, "pkg.pure.* -> sqlalchemy\n")
        rule = import_linter_rule(
            "pkg-pure",
            baseline=Baseline(BASELINE_FILE, 1),
            allowed=["pkg.models -> sqlalchemy"],
        )

        self.assertEqual(
            self.messages(rule),
            [
                "[ex.r] enforcer: contract 'pkg-pure' ignores "
                "pkg.pure.* -> sqlalchemy, a wildcard that would also ignore "
                "imports added later. Fix: list each import by its full module "
                "names."
            ],
        )

    def test_an_allowed_import_must_not_use_a_wildcard(self) -> None:
        self.repo.edit(
            "pyproject.toml",
            '"pkg.models -> sqlalchemy",',
            '"pkg.models.* -> sqlalchemy",',
        )
        rule = import_linter_rule(
            "pkg-pure",
            baseline=Baseline(BASELINE_FILE, 1),
            allowed=["pkg.models.* -> sqlalchemy"],
            sha256=fingerprint(CONFIG, "pkg-pure"),
        )

        self.assertEqual(
            self.messages(rule),
            [
                "[ex.r] enforcer: contract 'pkg-pure' ignores "
                "pkg.models.* -> sqlalchemy, a wildcard that would also ignore "
                "imports added later. Fix: list each import by its full module "
                "names."
            ],
        )

    def test_a_changed_contract_fails_until_the_rule_pins_it_again(self) -> None:
        self.repo.edit(
            "pyproject.toml",
            'source_modules = ["pkg.pure"]',
            'source_modules = ["pkg.pure.validators"]',
        )
        changed = fingerprint(self.repo.read("pyproject.toml"), "pkg-pure")
        rule = import_linter_rule(
            "pkg-pure",
            baseline=Baseline(BASELINE_FILE, 1),
            allowed=["pkg.models -> sqlalchemy"],
        )

        self.assertEqual(
            self.messages(rule),
            [
                "[ex.r] enforcer: contract 'pkg-pure' is not the definition the "
                "rule pins (enforcer.contract_sha256 is "
                f"{fingerprint(CONFIG, 'pkg-pure')}, the contract's is {changed}). "
                "Fix: if the change is intended, set enforcer.contract_sha256 = "
                f'"{changed}" in rules/registry.toml.'
            ],
        )

    def test_a_changed_top_level_setting_changes_every_contract(self) -> None:
        self.repo.edit(
            "pyproject.toml",
            'root_package = "pkg"\n',
            'root_package = "pkg"\nexclude_type_checking_imports = true\n',
        )

        messages = self.messages(import_linter_rule("pkg-layers"))

        self.assertEqual(len(messages), 1)
        self.assertIn("is not the definition the rule pins", messages[0])

    def test_a_rule_must_pin_its_contract(self) -> None:
        rule = import_linter_rule("pkg-layers", sha256="")

        self.assertEqual(
            self.messages(rule),
            [
                "[ex.r] enforcer: contract 'pkg-layers' is not the definition the "
                "rule pins (enforcer.contract_sha256 is empty, the contract's is "
                f"{fingerprint(CONFIG, 'pkg-layers')}). Fix: if the change is "
                "intended, set enforcer.contract_sha256 = "
                f'"{fingerprint(CONFIG, "pkg-layers")}" in rules/registry.toml.'
            ],
        )

    def test_an_empty_contract_or_config_is_reported(self) -> None:
        rule = import_linter_rule("", sha256="")

        self.assertEqual(
            self.messages(rule),
            [
                "[ex.r] enforcer: enforcer.config and enforcer.contract must name "
                "the config file and the contract's id. Fix: set both, for "
                'example config = "pyproject.toml".'
            ],
        )

    def test_ci_must_run_every_contract_from_the_named_config(self) -> None:
        ci = (CiRef(".github/workflows/pr.yml", "quality-guards", "lint-imports"),)
        for command, accepted in (
            ("uv run --frozen --extra dev lint-imports --config pyproject.toml", True),
            ("lint-imports --config pyproject.toml", True),
            ("lint-imports --config pyproject.toml --contract pkg-layers", False),
            ("lint-imports --config pyproject.toml || true", False),
            ("lint-imports", False),
            ("lint-imports --config pyproject.toml.bak", False),
        ):
            with self.subTest(command=command):
                self.repo.write(
                    ".github/workflows/pr.yml",
                    f"jobs:\n  quality-guards:\n    steps:\n      - run: {command}\n",
                )
                rule = dataclasses.replace(import_linter_rule("pkg-layers"), ci=ci)
                messages = self.messages(rule)
                expected = (
                    []
                    if accepted
                    else [
                        "[ex.r] enforcer: job 'quality-guards' in "
                        ".github/workflows/pr.yml runs Import Linter as "
                        f"'{command}', which may skip contracts or ignore failures. "
                        "Fix: run exactly 'lint-imports --config pyproject.toml', "
                        "optionally after 'uv run ...'."
                    ]
                )
                self.assertEqual(messages, expected)

    def test_a_make_target_the_job_runs_must_run_every_contract_too(self) -> None:
        ci = (CiRef(".github/workflows/pr.yml", "quality-guards", "lint-imports"),)
        self.repo.write(
            ".github/workflows/pr.yml",
            "jobs:\n  quality-guards:\n    steps:\n      - run: make quality\n",
        )
        for command, accepted in (
            ("uv run --frozen --extra dev lint-imports --config pyproject.toml", True),
            ("lint-imports --config pyproject.toml || true", False),
            # make ignores the failure of a command with the - prefix.
            ("-lint-imports --config pyproject.toml", False),
        ):
            with self.subTest(command=command):
                self.repo.write(
                    "Makefile",
                    "quality:\n\t$(MAKE) quality-check\n\n"
                    f"quality-check:\n\t{command}\n",
                )
                rule = dataclasses.replace(import_linter_rule("pkg-layers"), ci=ci)
                messages = self.messages(rule)
                expected = (
                    []
                    if accepted
                    else [
                        "[ex.r] enforcer: job 'quality-guards' in "
                        ".github/workflows/pr.yml runs Import Linter as "
                        f"'{command}', which may skip contracts or ignore failures. "
                        "Fix: run exactly 'lint-imports --config pyproject.toml', "
                        "optionally after 'uv run ...'."
                    ]
                )
                self.assertEqual(messages, expected)

    def test_a_config_that_is_not_toml_is_reported(self) -> None:
        self.repo.write("setup.cfg", "[importlinter]\nroot_package = pkg\n")

        self.assertEqual(
            self.messages(
                dataclasses.replace(
                    import_linter_rule("pkg-layers"),
                    enforcer=Enforcer(
                        Kind.IMPORT_LINTER,
                        {"config": "setup.cfg", "contract": "pkg-layers"},
                    ),
                )
            ),
            [
                "[ex.r] enforcer: setup.cfg is not a TOML file, so the rules "
                "guard can't read its contracts. Fix: keep the Import Linter "
                "contracts in [tool.importlinter] in pyproject.toml."
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


class TestUnregisteredContracts(unittest.TestCase):
    def test_a_contract_no_rule_references_is_a_hidden_rule(self) -> None:
        # Reported in the order pyproject.toml lists the contracts.
        with Repo({"pyproject.toml": CONFIG}) as repo:
            hidden = [
                message for message in repo.messages() if "hidden-rule" in message
            ]

        self.assertEqual(
            hidden,
            [
                "[registry] hidden-rule: Import Linter contract 'pkg-pure' in "
                "pyproject.toml has no rule. Fix: add a [[rule]] with "
                'enforcer.kind = "import-linter" and enforcer.contract = '
                '"pkg-pure".',
                "[registry] hidden-rule: Import Linter contract 'pkg-layers' in "
                "pyproject.toml has no rule. Fix: add a [[rule]] with "
                'enforcer.kind = "import-linter" and enforcer.contract = '
                '"pkg-layers".',
            ],
        )

    def test_a_contract_without_an_id_is_a_hidden_rule(self) -> None:
        config = '[tool.importlinter]\nroot_package = "pkg"\n\n'
        config += '[[tool.importlinter.contracts]]\nname = "Layers"\ntype = "layers"\n'
        with Repo({"pyproject.toml": config}) as repo:
            hidden = [
                message for message in repo.messages() if "hidden-rule" in message
            ]

        self.assertEqual(
            hidden,
            [
                "[registry] hidden-rule: Import Linter contract 'Layers' in "
                "pyproject.toml has no id, so no rule can reference it. Fix: give "
                "it an id and add a [[rule]] with enforcer.kind = "
                '"import-linter" that names it.'
            ],
        )


if __name__ == "__main__":
    unittest.main()
