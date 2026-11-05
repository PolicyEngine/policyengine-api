"""Tests for the v2-layers quality guard (scripts/rules/v2_layers.py)."""

from __future__ import annotations

import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path

from scripts.rules.load import load_registry
from scripts.rules.v2_layers import (
    CONNECTORS_RULE,
    FILES_RULE,
    PURE_RULE,
    ROUTES_RULE,
    SERVICES_RULE,
    SESSION_RULE,
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
            str(finding) for finding in scan(root, ()) if finding.rule_id == rule_id
        }


def _all_findings(files: dict[str, str], exceptions: tuple[str, ...]) -> set[str]:
    """Return every finding as ``<rule id>: <path> <detail>``."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _write_files(files, root)
        return {f"{finding.rule_id}: {finding}" for finding in scan(root, exceptions)}


def _assert_proof(test: unittest.TestCase, rule_id: str) -> None:
    """Each tree gives exactly its expected findings, each under its rule.

    A tree's ``exceptions`` list the files a ``[[rule.exception]]`` for
    api.v2.files-assigned-to-layers would name.
    """
    for fixture in ("bad_tree.toml", "good_tree.toml"):
        tree = tomllib.loads((FIXTURES / rule_id / fixture).read_text())
        exceptions = tuple(tree.get("exceptions", ()))
        with test.subTest(fixture=fixture):
            test.assertEqual(
                _all_findings(tree["files"], exceptions),
                set(tree["expected_findings"]),
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

    def test_rule_proof_pure_modules_no_session_calls(self) -> None:
        _assert_proof(self, PURE_RULE)

    def test_rule_proof_session_modules_no_data_access(self) -> None:
        _assert_proof(self, SESSION_RULE)


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
            "policyengine_api/services/v2/metadata/process_state.py": "process-state",
            "policyengine_api/fastapi_routes/v2/households/document_models.py": (
                "http-model"
            ),
            "policyengine_api/fastapi_routes/v2/reports/"
            "household_response_models.py": "http-model",
            "policyengine_api/fastapi_routes/v2/errors_support.py": "http-support",
            "policyengine_api/fastapi_routes/v2/metadata/route_support.py": (
                "http-support"
            ),
        }
        for path, layer in cases.items():
            with self.subTest(path=path):
                self.assertEqual(assign_layer(path, ()), layer)

    def test_other_names_have_no_layer_unless_excepted(self) -> None:
        unnamed = "policyengine_api/fastapi_routes/v2/metadata/response_cache.py"
        misnamed_connector = (
            "policyengine_api/services/v2/policies/database_connectors/helpers.py"
        )
        support_outside_routes = "policyengine_api/services/v2/policies/x_support.py"

        self.assertIsNone(assign_layer(unnamed, ()))
        self.assertIsNone(assign_layer(misnamed_connector, ()))
        self.assertIsNone(assign_layer(support_outside_routes, ()))
        self.assertEqual(assign_layer(unnamed, (unnamed,)), "excepted")

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
            def handle(session, read_session, names: set, cache: dict):
                names.add("a")
                cache.get("b")
                read_session.exec("c")
                session.get("d")
        """

        self.assertEqual(
            _findings({ROUTE: source}, ROUTES_RULE),
            {
                f"{ROUTE} calls read_session.exec",
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
            {f"{SERVICE} calls sqlalchemy.text", f"{SERVICE} imports sqlalchemy"},
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


class TestEveryLayerIsChecked(unittest.TestCase):
    """Only connectors and session modules may touch a session (review findings)."""

    SESSION_WORK = """
        from sqlmodel import select


        def work(session, row):
            session.add(row)
            session.commit()
            return session.exec(select(row))
    """

    def test_validators_transformations_types_and_process_state_touch_no_session(
        self,
    ) -> None:
        for path in (
            "policyengine_api/services/v2/policies/validators.py",
            "policyengine_api/services/v2/policies/transformations.py",
            "policyengine_api/services/v2/policies/types.py",
            "policyengine_api/services/v2/policies/__init__.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    _findings({path: self.SESSION_WORK}, PURE_RULE),
                    {
                        f"{path} calls session.add",
                        f"{path} calls session.commit",
                        f"{path} calls session.exec",
                        f"{path} calls sqlmodel.select",
                        f"{path} imports sqlmodel.select",
                    },
                )

    def test_a_connector_package_init_is_a_connector(self) -> None:
        path = "policyengine_api/services/v2/policies/database_connectors/__init__.py"

        self.assertEqual(
            _findings({path: self.SESSION_WORK}, CONNECTORS_RULE),
            {f"{path} calls session.commit"},
        )

    def test_the_repository_session_factories_count(self) -> None:
        route_source = """
            from policyengine_api.data.orm import get_v1_session_factory
            from policyengine_api.data.v2.database import build_v2_session_factory


            def route(database_session):
                with database_session.transaction() as session:
                    get_v1_session_factory()
                    build_v2_session_factory()
        """
        connector_source = """
            from policyengine_api.data.orm import get_v1_engine


            def read():
                return get_v1_engine()
        """

        self.assertEqual(
            _findings({ROUTE: route_source}, ROUTES_RULE),
            {
                f"{ROUTE} calls build_v2_session_factory",
                f"{ROUTE} calls database_session.transaction",
                f"{ROUTE} calls get_v1_session_factory",
                f"{ROUTE} imports policyengine_api.data.orm",
                f"{ROUTE} imports policyengine_api.data.v2.database",
            },
        )
        self.assertEqual(
            _findings({CONNECTOR: connector_source}, CONNECTORS_RULE),
            {
                f"{CONNECTOR} calls get_v1_engine",
                f"{CONNECTOR} imports policyengine_api.data.orm",
            },
        )

    def test_services_import_only_the_session_type_and_errors_from_sql_packages(
        self,
    ) -> None:
        source = """
            from typing import TYPE_CHECKING

            from sqlalchemy import and_, func, or_
            from sqlalchemy.exc import IntegrityError
            from sqlmodel import col

            if TYPE_CHECKING:
                from sqlmodel import Session


            def build(Policy, ids):
                Policy.__table__.select()
                return and_(col(Policy.id).in_(ids), or_(func.lower(Policy.name)))
        """

        self.assertEqual(
            _findings({SERVICE: source}, SERVICES_RULE),
            {
                f"{SERVICE} calls Policy.__table__.select",
                f"{SERVICE} calls sqlalchemy.and_",
                f"{SERVICE} calls sqlalchemy.func.lower",
                f"{SERVICE} calls sqlalchemy.or_",
                f"{SERVICE} calls sqlmodel.col",
                f"{SERVICE} imports sqlalchemy.and_",
                f"{SERVICE} imports sqlalchemy.func",
                f"{SERVICE} imports sqlalchemy.or_",
                f"{SERVICE} imports sqlmodel.col",
            },
        )

    def test_names_that_only_contain_session_are_not_sessions(self) -> None:
        source = """
            @sessions_router.get("/sessions")
            def route(request, session_ids: set):
                session_ids.add(1)
                request.session.get("user")
                return self._sessions_by_country.get("us")
        """

        self.assertEqual(_findings({ROUTE: source}, ROUTES_RULE), set())


class TestSecondReview(unittest.TestCase):
    """Cases from the second review round."""

    def test_routes_and_pure_layers_may_call_no_session_method_at_all(self) -> None:
        source = """
            def handle(session, row):
                session.get_one(row, 1)
                session.bulk_save_objects([row])
                session.connection()
                session.expunge(row)
        """
        validator = "policyengine_api/services/v2/policies/validators.py"

        for path, rule_id in ((ROUTE, ROUTES_RULE), (validator, PURE_RULE)):
            with self.subTest(path=path):
                self.assertEqual(
                    _findings({path: source}, rule_id),
                    {
                        f"{path} calls session.bulk_save_objects",
                        f"{path} calls session.connection",
                        f"{path} calls session.expunge",
                        f"{path} calls session.get_one",
                    },
                )

    def test_services_and_connectors_know_every_relevant_session_method(self) -> None:
        service_source = """
            class Service:
                def run(self, rows):
                    with self._database_session.transaction():
                        self._session.get_one(rows, 1)
                        self._session.bulk_insert_mappings(rows, [])
        """
        connector_source = """
            def write(session):
                session.reset()
                session.invalidate()
        """

        self.assertEqual(
            _findings({SERVICE: service_source}, SERVICES_RULE),
            {
                f"{SERVICE} calls _session.bulk_insert_mappings",
                f"{SERVICE} calls _session.get_one",
            },
        )
        self.assertEqual(
            _findings({CONNECTOR: connector_source}, CONNECTORS_RULE),
            {
                f"{CONNECTOR} calls session.invalidate",
                f"{CONNECTOR} calls session.reset",
            },
        )

    def test_an_excepted_file_gets_its_directory_s_strictest_checks(self) -> None:
        client = "policyengine_api/services/v2/household_calculations/client.py"
        helper = "policyengine_api/fastapi_routes/v2/metadata/legacy_helper.py"
        process_state = "policyengine_api/services/v2/metadata/process_state.py"
        files = {
            client: (
                "from policyengine_api.data.orm import get_v1_session_factory\n"
                "def load(session):\n"
                "    get_v1_session_factory()\n"
                "    return session.exec(1)\n"
            ),
            helper: "def keep(session, row):\n    session.add(row)\n",
            process_state: "def load(session):\n    return session.exec(1)\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_files(files, root)
            found = {
                (finding.rule_id, str(finding))
                for finding in scan(root, (client, helper))
            }

        self.assertEqual(
            found,
            {
                (PURE_RULE, f"{client} calls get_v1_session_factory"),
                (PURE_RULE, f"{client} calls session.exec"),
                (PURE_RULE, f"{client} imports policyengine_api.data.orm"),
                (PURE_RULE, f"{process_state} calls session.exec"),
                (ROUTES_RULE, f"{helper} calls session.add"),
            },
        )

    def test_a_session_module_below_a_resource_package_has_no_layer(self) -> None:
        nested = "policyengine_api/services/v2/metadata/catalogs/database_session.py"

        self.assertIsNone(assign_layer(nested, {}))
        self.assertEqual(
            assign_layer(
                "policyengine_api/services/v2/metadata/database_session.py", {}
            ),
            "session",
        )

    def test_every_call_into_sqlalchemy_counts_except_its_exceptions(self) -> None:
        source = """
            import sqlalchemy.exc


            def build(Policy):
                try:
                    return sqlalchemy.and_(sqlalchemy.func.lower(Policy.name) == "x")
                except sqlalchemy.exc.IntegrityError:
                    raise sqlalchemy.exc.IntegrityError("x", None, None)
        """

        self.assertEqual(
            _findings({SERVICE: source}, SERVICES_RULE),
            {
                f"{SERVICE} calls sqlalchemy.and_",
                f"{SERVICE} calls sqlalchemy.func.lower",
            },
        )

    def test_web_sessions_and_clients_are_not_database_sessions(self) -> None:
        source = """
            def handle(self, http_request, requests_session):
                self.request.session.get("user")
                http_request.session.get("user")
                self._client_session.get("https://example.org")
                requests_session.get("https://example.org")
        """

        self.assertEqual(_findings({ROUTE: source}, ROUTES_RULE), set())

    def test_only_a_builder_called_on_a_table_counts(self) -> None:
        source = """
            from policyengine_api.data.v2.models import Policy


            def build(rows):
                Policy.__table__.insert().values(name="x")
                Policy.__table__.columns.values()
                rows[Policy.__table__.name].values()
        """

        self.assertEqual(
            _findings({SERVICE: source}, SERVICES_RULE),
            {f"{SERVICE} calls Policy.__table__.insert"},
        )


class TestThirdReview(unittest.TestCase):
    """Cases from the third review round."""

    def test_injected_session_factories_and_containers_open_sessions(self) -> None:
        connector_source = """
            def create(session_factory, database_session, row):
                with session_factory.begin() as session:
                    session.add(row)
                with database_session.transaction() as session:
                    session.add(row)


            class Writer:
                def write(self, row):
                    with self._session_factory() as session:
                        session.add(row)
        """
        route_source = """
            def route(session_factory, row):
                with session_factory.begin() as db:
                    return db
        """

        self.assertEqual(
            _findings({CONNECTOR: connector_source}, CONNECTORS_RULE),
            {
                f"{CONNECTOR} calls _session_factory",
                f"{CONNECTOR} calls database_session.transaction",
                f"{CONNECTOR} calls session_factory.begin",
            },
        )
        self.assertEqual(
            _findings({ROUTE: route_source}, ROUTES_RULE),
            {f"{ROUTE} calls session_factory.begin"},
        )

    def test_request_session_data_is_recognised_by_its_owner(self) -> None:
        route_source = """
            def route(req, websocket, request_context, row):
                req.session.get("user")
                websocket.session.get("user")
                request_context.session.add(row)
        """
        service_source = """
            def run(request_session, statement):
                return request_session.exec(statement)
        """

        self.assertEqual(
            _findings({ROUTE: route_source}, ROUTES_RULE),
            {f"{ROUTE} calls session.add"},
        )
        self.assertEqual(
            _findings({SERVICE: service_source}, SERVICES_RULE),
            {f"{SERVICE} calls request_session.exec"},
        )


class TestBaselineAndExceptions(unittest.TestCase):
    """run_check compares findings with the baseline and checks the exceptions."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def _registry(
        self,
        baseline_count: int | None,
        exceptions: tuple[str, ...] = (),
        exception_fields: str = "expires = 2099-01-01\n",
    ) -> str:
        rules = []
        for rule_id in (FILES_RULE, ROUTES_RULE, SERVICES_RULE, CONNECTORS_RULE):
            ratcheted = rule_id == ROUTES_RULE and baseline_count is not None
            baseline = (
                f'[rule.baseline]\nfile = "{BASELINE_FILE}"\ncount = {baseline_count}\n'
                if ratcheted
                else ""
            )
            excepted = "".join(
                f'[[rule.exception]]\npath = "{path}"\nreason = "Generated."\n'
                + exception_fields
                for path in (exceptions if rule_id == FILES_RULE else ())
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
                + excepted
            )
        header = (
            'schema_version = 1\nrepo = "example"\n\n'
            '[[category]]\nid = "layers"\ntitle = "Layers"\n'
        )
        return header + "".join(rules)

    def _messages(self) -> list[str]:
        _, problems = load_registry(self.root)
        self.assertEqual([str(problem) for problem in problems], [])
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

    def test_each_occurrence_needs_its_own_baseline_entry(self) -> None:
        _write_files(
            {
                ROUTE: (
                    "from sqlalchemy.exc import SQLAlchemyError\n"
                    "def later():\n"
                    "    from sqlalchemy.exc import IntegrityError\n"
                ),
                "rules/registry.toml": self._registry(1),
                BASELINE_FILE: f"{ROUTE} imports sqlalchemy.exc\n",
            },
            self.root,
        )

        self.assertEqual(
            self._messages(),
            [
                f"[{ROUTES_RULE}] v2-layers: {ROUTE} imports sqlalchemy.exc (2 "
                "occurrences, the baseline tolerates 1). Fix: v2 route modules call "
                "one service method and map its typed failures to HTTP; move session "
                "and SQL work into the service and its connectors "
                "(docs/engineering/skills/v2-code-organization.md)."
            ],
        )

    def test_a_duplicated_baseline_entry_is_stale(self) -> None:
        _write_files(
            {
                ROUTE: "from sqlalchemy.exc import SQLAlchemyError\n",
                "rules/registry.toml": self._registry(2),
                BASELINE_FILE: (
                    f"{ROUTE} imports sqlalchemy.exc\n{ROUTE} imports sqlalchemy.exc\n"
                ),
            },
            self.root,
        )

        self.assertEqual(
            self._messages(),
            [
                f"[{ROUTES_RULE}] v2-layers: baseline entry no longer applies: "
                f"{ROUTE} imports sqlalchemy.exc (1 occurrence, the baseline lists "
                f"2). Fix: remove it from {BASELINE_FILE} and lower the rule's "
                "baseline count."
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
                "transformations.py, types.py or process_state.py in a resource "
                "package under services/v2, database_session.py directly in "
                "one, or database_connectors/<creates|reads|updates|deletes>"
                "[_name].py directly in its database_connectors package), or, "
                "if it can't be renamed, add a [[rule.exception]] for "
                "api.v2.files-assigned-to-layers to rules/registry.toml with its "
                "path, a reason and an expires date."
            ],
        )

    def test_an_unassigned_connector_file_must_be_renamed(self) -> None:
        unassigned = (
            "policyengine_api/services/v2/policies/database_connectors/helpers.py"
        )
        _write_files(
            {unassigned: "", "rules/registry.toml": self._registry(None)}, self.root
        )

        self.assertEqual(
            self._messages(),
            [
                f"[{FILES_RULE}] v2-layers: {unassigned} matches no v2 layer. Fix: "
                "name it after its operation, "
                "<creates|reads|updates|deletes>[_name].py; an exception can't "
                "stand in, because rule api.v2.crud-checks-cover-every-resource "
                "also checks connector names."
            ],
        )

    def test_an_unassigned_route_file_is_told_the_route_names(self) -> None:
        unassigned = "policyengine_api/fastapi_routes/v2/metadata/helpers.py"
        _write_files(
            {unassigned: "", "rules/registry.toml": self._registry(None)}, self.root
        )

        self.assertEqual(
            self._messages(),
            [
                f"[{FILES_RULE}] v2-layers: {unassigned} matches no v2 layer. Fix: "
                "name it after its layer (routes.py, <name>_routes.py, "
                "<name>_models.py or <name>_support.py), or, if it can't be "
                "renamed, add a [[rule.exception]] for "
                "api.v2.files-assigned-to-layers to rules/registry.toml with its "
                "path, a reason and an expires date."
            ],
        )

    def test_an_exception_gives_no_layer_but_the_strictest_checks(self) -> None:
        client = "policyengine_api/services/v2/household_calculations/client.py"
        _write_files(
            {
                client: "def load(session):\n    return session.get(1)\n",
                "rules/registry.toml": self._registry(None, (client,)),
            },
            self.root,
        )

        self.assertEqual(
            self._messages(),
            [
                f"[{PURE_RULE}] v2-layers: {client} calls session.get. Fix: "
                "validators, transformations and types work on values and loaded "
                "rows; load them in a connector and pass them in from the service "
                "(docs/engineering/skills/v2-code-organization.md)."
            ],
        )

    def test_an_exception_ends_on_its_expires_date_and_covers_the_whole_file(
        self,
    ) -> None:
        client = "policyengine_api/services/v2/household_calculations/client.py"
        prefix = f"[{FILES_RULE}] v2-layers: rules/registry.toml excepts {client}"
        no_date = (
            f"{prefix} from {FILES_RULE}, but the exception has no expires date. "
            "Fix: give it an expires date by which the file is renamed."
        )
        unassigned = f"[{FILES_RULE}] v2-layers: {client} matches no v2 layer."
        for fields, field_name, ends in (
            ('category = "forever"\n', "category", False),
            ('removal = "never"\n', "removal", False),
            ('match = "session.get"\nexpires = 2099-01-01\n', "match", True),
        ):
            with self.subTest(field=field_name):
                _write_files(
                    {
                        client: "",
                        "rules/registry.toml": self._registry(
                            None, (client,), exception_fields=fields
                        ),
                    },
                    self.root,
                )
                expected = [
                    f"{prefix} from {FILES_RULE}, but the exception sets "
                    f"{field_name}, which this rule doesn't read. Fix: remove it; "
                    "a files-rule exception covers the whole file and ends on "
                    "its expires date."
                ]
                if not ends:
                    expected.append(no_date)

                messages = self._messages()

                self.assertEqual(
                    sorted(m for m in messages if not m.startswith(unassigned)),
                    sorted(expected),
                )
                self.assertTrue(any(m.startswith(unassigned) for m in messages))

    def test_a_connector_module_cannot_be_excepted(self) -> None:
        helper = "policyengine_api/services/v2/policies/database_connectors/helpers.py"
        _write_files(
            {helper: "", "rules/registry.toml": self._registry(None, (helper,))},
            self.root,
        )

        self.assertIn(
            f"[{FILES_RULE}] v2-layers: rules/registry.toml excepts {helper} from "
            f"{FILES_RULE}, but a database_connectors module must be named after "
            "its operation (rule api.v2.crud-checks-cover-every-resource). Fix: "
            "rename it to <creates|reads|updates|deletes>[_name].py and remove "
            "the exception.",
            self._messages(),
        )

    def test_exceptions_must_name_one_existing_v2_file_without_a_layer(self) -> None:
        named = ROUTE
        missing = "policyengine_api/services/v2/policies/gone.py"
        pattern = "policyengine_api/services/v2/*/client.py"
        outside = "policyengine_api/libs/user_auth.py"
        _write_files(
            {
                named: "",
                outside: "",
                "rules/registry.toml": self._registry(
                    None, (named, missing, pattern, outside)
                ),
            },
            self.root,
        )
        prefix = f"[{FILES_RULE}] v2-layers: rules/registry.toml excepts"
        one_file = (
            "which is not one file under policyengine_api/services/v2 or "
            "policyengine_api/fastapi_routes/v2. Fix: name one file there, or "
            "remove the exception."
        )

        self.assertEqual(
            sorted(self._messages()),
            sorted(
                [
                    f"{prefix} {named} from {FILES_RULE}, but its name already "
                    "gives it a layer. Fix: remove the exception.",
                    f"{prefix} {missing} from {FILES_RULE}, but it does not "
                    "exist. Fix: remove the exception.",
                    f"{prefix} {pattern} from {FILES_RULE}, {one_file}",
                    f"{prefix} {outside} from {FILES_RULE}, {one_file}",
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
