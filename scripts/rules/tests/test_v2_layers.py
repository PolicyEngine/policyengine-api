"""Tests for the v2-layers quality guard (scripts/rules/v2_layers.py)."""

from __future__ import annotations

import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path

from scripts.rules.v2_layers import (
    CONNECTORS_RULE,
    FILES_RULE,
    ROUTES_RULE,
    SERVICES_RULE,
    assign_layer,
    run_check,
    scan,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "rules" / "fixtures"
ROUTE = "policyengine_api/fastapi_routes/v2/policies/routes.py"
SERVICE = "policyengine_api/services/v2/policies/services.py"
CONNECTOR = "policyengine_api/services/v2/policies/database_connectors/creates.py"
BASELINE_FILE = "rules/baselines/v2-layers-routes.txt"


def _write_files(files: dict[str, str], root: Path) -> None:
    for relative_path, source in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source))


def _findings(files: dict[str, str], rule_id: str) -> set[str]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _write_files(files, root)
        return {
            str(finding) for finding in scan(root, {}) if finding.rule_id == rule_id
        }


def _assert_proof(test: unittest.TestCase, rule_id: str) -> None:
    for fixture in ("bad_tree.toml", "good_tree.toml"):
        tree = tomllib.loads((FIXTURES / rule_id / fixture).read_text())
        with test.subTest(fixture=fixture):
            test.assertEqual(
                _findings(tree["files"], rule_id), set(tree["expected_findings"])
            )
    bad = tomllib.loads((FIXTURES / rule_id / "bad_tree.toml").read_text())
    test.assertTrue(bad["expected_findings"], "the bad fixture must be rejected")


class TestV2LayersProof(unittest.TestCase):
    """Proofs: a bad tree gives exactly its expected findings, a good tree none."""

    def test_rule_proof_files_assigned_to_layers(self) -> None:
        _assert_proof(self, FILES_RULE)

    def test_rule_proof_routes_no_sessions_or_sql(self) -> None:
        _assert_proof(self, ROUTES_RULE)

    def test_rule_proof_services_no_sql(self) -> None:
        _assert_proof(self, SERVICES_RULE)

    def test_rule_proof_connectors_never_commit(self) -> None:
        _assert_proof(self, CONNECTORS_RULE)


class TestLayerAssignment(unittest.TestCase):
    def test_files_are_assigned_by_name(self) -> None:
        cases = {
            "policyengine_api/services/v2/__init__.py": "package",
            "policyengine_api/services/v2/policies/services.py": "service",
            "policyengine_api/services/v2/policies/validators.py": "validator",
            "policyengine_api/services/v2/policies/transformations.py": (
                "transformation"
            ),
            "policyengine_api/services/v2/policies/types.py": "types",
            "policyengine_api/services/v2/policies/database_session.py": "session",
            "policyengine_api/services/v2/policies/database_connectors/reads.py": (
                "connector"
            ),
            "policyengine_api/services/v2/metadata/database_connectors/"
            "reads_parameter_tree.py": "connector",
            "policyengine_api/fastapi_routes/v2/routes.py": "route",
            "policyengine_api/fastapi_routes/v2/policies/routes.py": "route",
            "policyengine_api/fastapi_routes/v2/metadata/catalog_routes.py": "route",
            "policyengine_api/fastapi_routes/v2/policies/request_models.py": (
                "http-model"
            ),
            "policyengine_api/fastapi_routes/v2/policies/response_models.py": (
                "http-model"
            ),
        }
        for path, layer in cases.items():
            with self.subTest(path=path):
                self.assertEqual(assign_layer(path, {}), layer)

    def test_other_names_have_no_layer_unless_the_manifest_assigns_one(self) -> None:
        unnamed = "policyengine_api/fastapi_routes/v2/metadata/response_cache.py"
        misnamed_connector = (
            "policyengine_api/services/v2/policies/database_connectors/helpers.py"
        )

        self.assertIsNone(assign_layer(unnamed, {}))
        self.assertIsNone(assign_layer(misnamed_connector, {}))
        self.assertEqual(
            assign_layer(unnamed, {unnamed: "http-support"}), "http-support"
        )

    def test_every_file_in_the_repository_has_a_layer(self) -> None:
        violations = [
            str(violation)
            for violation in run_check(REPO_ROOT)
            if violation.rule_id == FILES_RULE
        ]

        self.assertEqual(violations, [])


class TestCallChecks(unittest.TestCase):
    def test_only_calls_on_a_session_count_as_session_calls(self) -> None:
        source = """
            def handle(session, request_session, names: set, cache: dict):
                names.add("a")
                cache.get("b")
                request_session.exec("c")
                session.get("d")
        """

        self.assertEqual(
            _findings({ROUTE: source}, ROUTES_RULE),
            {
                f"{ROUTE} calls request_session.exec",
                f"{ROUTE} calls session.get",
            },
        )

    def test_sql_builders_count_only_when_imported_from_sqlalchemy_or_sqlmodel(
        self,
    ) -> None:
        source = """
            import sqlalchemy as sa
            from policyengine_api.services.v2.policies.queries import select


            def handle():
                select("local helper")
                return sa.text("raw")
        """

        self.assertEqual(
            _findings({SERVICE: source}, SERVICES_RULE),
            {f"{SERVICE} calls sqlalchemy.text"},
        )

    def test_imports_under_type_checking_count(self) -> None:
        source = """
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                from policyengine_api.services.v2.policies.database_session import (
                    PolicyDatabaseSession,
                )
        """

        self.assertEqual(
            _findings({ROUTE: source}, ROUTES_RULE),
            {f"{ROUTE} imports policyengine_api.services.v2.policies.database_session"},
        )

    def test_package_and_relative_imports_are_resolved(self) -> None:
        source = """
            from policyengine_api.data.v2 import database
            from .. import database_session
        """

        self.assertEqual(
            _findings({CONNECTOR: source}, CONNECTORS_RULE),
            {
                f"{CONNECTOR} imports policyengine_api.data.v2.database",
                f"{CONNECTOR} imports "
                "policyengine_api.services.v2.policies.database_session",
            },
        )

    def test_connectors_may_add_and_flush_but_not_end_a_transaction(self) -> None:
        source = """
            def write(session, row):
                session.add(row)
                session.flush()
                session.rollback()
                session.close()
        """

        self.assertEqual(
            _findings({CONNECTOR: source}, CONNECTORS_RULE),
            {f"{CONNECTOR} calls session.rollback", f"{CONNECTOR} calls session.close"},
        )


class TestBaselineAndManifest(unittest.TestCase):
    """run_check compares findings with the rule's baseline and checks the manifest."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def _registry(self, baseline_count: int | None) -> str:
        rules = []
        for rule_id in (FILES_RULE, ROUTES_RULE, SERVICES_RULE, CONNECTORS_RULE):
            ratcheted = rule_id == ROUTES_RULE and baseline_count is not None
            baseline = (
                f'[rule.baseline]\nfile = "{BASELINE_FILE}"\ncount = {baseline_count}\n'
                if ratcheted
                else ""
            )
            rules.append(
                textwrap.dedent(
                    f"""
                    [[rule]]
                    id = "{rule_id}"
                    category = "layers"
                    statement = "A statement."
                    rationale = "docs/guide.md"
                    scope = ["policyengine_api/**/*.py"]
                    tier = "mechanical"
                    status = "{"ratcheted" if ratcheted else "enforced"}"
                    autofix = false
                    [rule.enforcer]
                    kind = "quality-guard"
                    name = "v2-layers"
                    [[rule.ci]]
                    workflow = ".github/workflows/pr.yml"
                    job = "quality-guards"
                    invocation = "run_quality_guards.py"
                    """
                )
                + baseline
            )
        header = (
            'schema_version = 1\nrepo = "example"\n\n'
            '[[category]]\nid = "layers"\ntitle = "Layers"\n'
        )
        return header + "".join(rules)

    def _messages(self) -> list[str]:
        return [str(violation) for violation in run_check(self.root)]

    def test_a_finding_the_baseline_lists_passes(self) -> None:
        _write_files({ROUTE: "from sqlalchemy.exc import SQLAlchemyError\n"}, self.root)
        _write_files(
            {
                "rules/registry.toml": self._registry(1),
                BASELINE_FILE: f"{ROUTE} imports sqlalchemy.exc\n",
            },
            self.root,
        )

        self.assertEqual(self._messages(), [])

    def test_a_finding_the_baseline_does_not_list_fails(self) -> None:
        _write_files({ROUTE: "from sqlalchemy.exc import SQLAlchemyError\n"}, self.root)
        _write_files({"rules/registry.toml": self._registry(None)}, self.root)

        self.assertEqual(
            self._messages(),
            [
                f"[{ROUTES_RULE}] v2-layers: {ROUTE} imports sqlalchemy.exc. Fix: "
                "v2 route modules call one service method and map its typed "
                "failures to HTTP; move session and SQL work into the service and "
                "its connectors (docs/engineering/skills/v2-code-organization.md)."
            ],
        )

    def test_a_baseline_entry_that_no_longer_applies_fails(self) -> None:
        _write_files({ROUTE: "def route():\n    return 1\n"}, self.root)
        _write_files(
            {
                "rules/registry.toml": self._registry(1),
                BASELINE_FILE: f"{ROUTE} imports sqlalchemy.exc\n",
            },
            self.root,
        )

        self.assertEqual(
            self._messages(),
            [
                f"[{ROUTES_RULE}] v2-layers: baseline entry no longer applies: "
                f"{ROUTE} imports sqlalchemy.exc. Fix: remove it from "
                f"{BASELINE_FILE} and lower the rule's baseline count."
            ],
        )

    def test_an_unassigned_file_fails_and_names_the_fix(self) -> None:
        unassigned = "policyengine_api/services/v2/policies/helpers.py"
        _write_files(
            {unassigned: "", "rules/registry.toml": self._registry(None)}, self.root
        )

        self.assertEqual(
            self._messages(),
            [
                f"[{FILES_RULE}] v2-layers: {unassigned} matches no v2 layer. Fix: "
                "name it after its layer (services.py, validators.py, "
                "transformations.py, types.py, database_session.py, "
                "database_connectors/<creates|reads|updates|deletes>[_name].py, "
                "routes.py, <name>_routes.py, request_models.py or "
                "response_models.py), or add it to rules/v2-layer-manifest.toml "
                "with its layer and a reason."
            ],
        )

    def test_manifest_entries_must_name_existing_unmatched_files_and_known_layers(
        self,
    ) -> None:
        cache = "policyengine_api/fastapi_routes/v2/metadata/response_cache.py"
        _write_files(
            {
                cache: "",
                ROUTE: "",
                "rules/registry.toml": self._registry(None),
                "rules/v2-layer-manifest.toml": textwrap.dedent(
                    f"""
                    [files."{cache}"]
                    layer = "cache"
                    reason = "Keeps serialized responses."

                    [files."{ROUTE}"]
                    layer = "route"
                    reason = "Named routes.py already."

                    [files."policyengine_api/services/v2/gone.py"]
                    layer = "service"
                    reason = "Removed."
                    """
                ),
            },
            self.root,
        )

        self.assertEqual(
            sorted(self._messages()),
            sorted(
                [
                    f"[{FILES_RULE}] v2-layers: rules/v2-layer-manifest.toml gives "
                    f"{cache} the unknown layer 'cache'. Fix: use one of "
                    "connector, http-model, http-support, package, process-state, "
                    "route, service, session, transformation, types, validator.",
                    f"[{FILES_RULE}] v2-layers: rules/v2-layer-manifest.toml lists "
                    f"{ROUTE}, which its name already assigns to a layer. Fix: "
                    "remove the entry.",
                    f"[{FILES_RULE}] v2-layers: rules/v2-layer-manifest.toml lists "
                    "policyengine_api/services/v2/gone.py, which does not exist. "
                    "Fix: remove the entry.",
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
