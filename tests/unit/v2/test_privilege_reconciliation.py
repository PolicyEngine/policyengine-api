"""Planning, statements and reports for the v2 privilege reconcile script."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from policyengine_api.data.v2 import privilege_reconciliation
from policyengine_api.data.v2.privilege_reconciliation import (
    DefaultPrivilege,
    PrivilegeEntry,
    PublicRelations,
    ReconciliationPlan,
    grant_statements,
    plan_reconciliation,
    render_summary,
    verification_failures,
)
from policyengine_api.data.v2.privileges import (
    READ,
    READ_WRITE,
    TablePrivilege,
)

PROJECT_ROOT = Path(__file__).parents[3]
PROOF_FIXTURES = PROJECT_ROOT / "rules/fixtures/api.v2.deployed-privileges-match"
RUNTIME = "policyengine_v2_runtime"
STAGE12 = "policyengine_stage12_staging"


def _quote(identifier: str) -> str:
    return f'"{identifier}"'


def _declared() -> dict[str, dict[str, frozenset[TablePrivilege]]]:
    return {
        RUNTIME: {
            "users": READ_WRITE,
            "legacy_policy_mappings": READ,
            "reports": frozenset(),
        },
        STAGE12: {
            "users": frozenset(),
            "legacy_policy_mappings": frozenset(),
            "reports": frozenset(),
        },
    }


def _tables(names: set[str]) -> PublicRelations:
    return PublicRelations(tables=frozenset(names), views=frozenset())


def test_missing_declared_privileges_become_grants() -> None:
    plan = plan_reconciliation(
        _declared(),
        granted={RUNTIME: {"users": {"SELECT", "INSERT"}}},
        existing_roles={RUNTIME, STAGE12},
        existing_relations=_tables({"users", "legacy_policy_mappings", "reports"}),
    )

    assert plan.grants == (
        PrivilegeEntry(RUNTIME, "legacy_policy_mappings", "SELECT"),
        PrivilegeEntry(RUNTIME, "users", "DELETE"),
        PrivilegeEntry(RUNTIME, "users", "UPDATE"),
    )
    assert plan.undeclared == ()
    assert plan.missing_roles == ()
    assert plan.missing_tables == ()


def test_privileges_beyond_the_manifest_are_reported_not_granted_or_revoked() -> None:
    plan = plan_reconciliation(
        _declared(),
        granted={
            RUNTIME: {
                "users": {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"},
                "legacy_policy_mappings": {"SELECT", "INSERT"},
                "reports": {"SELECT"},
            },
            STAGE12: {"users": {"SELECT"}},
        },
        existing_roles={RUNTIME, STAGE12},
        existing_relations=_tables({"users", "legacy_policy_mappings", "reports"}),
    )

    assert plan.grants == ()
    assert plan.undeclared == (
        PrivilegeEntry(STAGE12, "users", "SELECT"),
        PrivilegeEntry(RUNTIME, "legacy_policy_mappings", "INSERT"),
        PrivilegeEntry(RUNTIME, "reports", "SELECT"),
        PrivilegeEntry(RUNTIME, "users", "TRUNCATE"),
    )
    assert grant_statements(plan, _quote) == []


def test_privileges_on_tables_outside_the_manifest_are_reported() -> None:
    plan = plan_reconciliation(
        _declared(),
        granted={RUNTIME: {"scratch_table": {"SELECT"}}},
        existing_roles={RUNTIME, STAGE12},
        existing_relations=_tables(
            {"users", "legacy_policy_mappings", "reports", "scratch_table"}
        ),
    )

    assert PrivilegeEntry(RUNTIME, "scratch_table", "SELECT") in plan.undeclared


def test_missing_roles_and_tables_are_recorded_and_block_the_plan() -> None:
    plan = plan_reconciliation(
        _declared(),
        granted={},
        existing_roles={RUNTIME},
        existing_relations=_tables({"users", "reports"}),
    )

    assert plan.missing_roles == (STAGE12,)
    assert plan.missing_tables == ("legacy_policy_mappings",)
    assert not plan.can_apply
    # Nothing is granted on a missing table or to a missing role.
    assert all(
        entry.role != STAGE12 and entry.table != "legacy_policy_mappings"
        for entry in plan.grants
    )


def test_a_relation_of_the_other_kind_does_not_satisfy_a_declaration() -> None:
    """A declared table must be a table, and a declared view must be a view.

    Before the rename, ``user_policies`` is a table, which must not satisfy the
    temporary view of that name; a view named like a declared table must not
    satisfy the table either.
    """
    declared = {
        RUNTIME: {"users": READ_WRITE, "user_policies": READ_WRITE, "reports": READ}
    }

    plan = plan_reconciliation(
        declared,
        granted={},
        existing_roles={RUNTIME},
        existing_relations=PublicRelations(
            tables=frozenset({"user_policies", "reports"}), views=frozenset({"users"})
        ),
        declared_views={"user_policies"},
    )

    assert plan.missing_tables == ("users",)
    assert plan.missing_views == ("user_policies",)
    assert not plan.can_apply


def test_declared_views_that_exist_as_views_are_granted() -> None:
    declared = {RUNTIME: {"users": READ, "user_policies": READ_WRITE}}

    plan = plan_reconciliation(
        declared,
        granted={},
        existing_roles={RUNTIME},
        existing_relations=PublicRelations(
            tables=frozenset({"users"}), views=frozenset({"user_policies"})
        ),
        declared_views={"user_policies"},
    )

    assert plan.can_apply
    assert plan.missing_tables == plan.missing_views == ()
    assert {entry.table for entry in plan.grants} == {"users", "user_policies"}


def test_summary_names_missing_views_separately_from_missing_tables() -> None:
    plan = ReconciliationPlan(
        grants=(),
        undeclared=(),
        missing_roles=(),
        missing_tables=("users",),
        missing_views=("user_policies",),
    )

    summary = render_summary(plan, (), deployment_environment="staging", applied=False)

    assert (
        "Declared tables missing from the database (nothing was granted): `users`"
        in summary
    )
    assert (
        "Declared views missing from the database (nothing was granted): "
        "`user_policies`" in summary
    )


def test_grant_statements_group_privileges_per_role_and_table() -> None:
    plan = ReconciliationPlan(
        grants=(
            PrivilegeEntry(RUNTIME, "users", "DELETE"),
            PrivilegeEntry(RUNTIME, "users", "UPDATE"),
            PrivilegeEntry(STAGE12, "reports", "SELECT"),
        ),
        undeclared=(),
        missing_roles=(),
        missing_tables=(),
    )

    assert grant_statements(plan, _quote) == [
        'GRANT SELECT ON TABLE "public"."reports" TO "policyengine_stage12_staging"',
        'GRANT DELETE, UPDATE ON TABLE "public"."users" TO "policyengine_v2_runtime"',
    ]


@pytest.mark.parametrize(
    "unsafe_identifier",
    ['users"; DROP TABLE users; --', "Users", "users table", ""],
)
def test_grant_statements_refuse_unsafe_identifiers(unsafe_identifier: str) -> None:
    plan = ReconciliationPlan(
        grants=(PrivilegeEntry(RUNTIME, unsafe_identifier, "SELECT"),),
        undeclared=(),
        missing_roles=(),
        missing_tables=(),
    )

    with pytest.raises(privilege_reconciliation.UnsafeIdentifierError):
        grant_statements(plan, _quote)


def test_verification_reports_each_declared_privilege_the_role_lacks() -> None:
    effective = {
        (RUNTIME, "users", "SELECT"),
        (RUNTIME, "users", "INSERT"),
        (RUNTIME, "users", "UPDATE"),
        (RUNTIME, "legacy_policy_mappings", "SELECT"),
    }

    failures = verification_failures(
        _declared(),
        lambda role, table, privilege: (role, table, privilege) in effective,
    )

    assert failures == [PrivilegeEntry(RUNTIME, "users", "DELETE")]


def test_summary_lists_grants_extras_and_default_privileges_without_secrets() -> None:
    plan = ReconciliationPlan(
        grants=(PrivilegeEntry(RUNTIME, "legacy_policy_mappings", "SELECT"),),
        undeclared=(PrivilegeEntry(RUNTIME, "policies", "DELETE"),),
        missing_roles=(),
        missing_tables=(),
    )
    defaults = (
        DefaultPrivilege(
            creating_role="policyengine_v2_migrator",
            schema="public",
            object_type="tables",
            grantee=RUNTIME,
            privileges=("DELETE", "INSERT", "SELECT", "UPDATE"),
        ),
    )

    summary = render_summary(
        plan, defaults, deployment_environment="staging", applied=True
    )

    assert "## v2 table privileges (staging)" in summary
    assert (
        "| `policyengine_v2_runtime` | `legacy_policy_mappings` | SELECT |" in summary
    )
    assert "| `policyengine_v2_runtime` | `policies` | DELETE |" in summary
    assert "reported, not revoked" in summary
    assert "`policyengine_v2_migrator`" in summary
    assert "postgresql" not in summary.lower().replace("postgresql's", "")


def _fixture_privileges(name: str) -> set[tuple[str, str, str]]:
    entries = json.loads((PROOF_FIXTURES / name).read_text(encoding="utf-8"))
    return {(entry["role"], entry["table"], entry["privilege"]) for entry in entries}


def test_rule_proof_deployed_privileges_match() -> None:
    """Proof for rule api.v2.deployed-privileges-match (rules/registry.toml).

    The bad fixture is production's runtime role before the #3977 fix: it
    lacked SELECT on ``legacy_policy_mappings``. The good fixture has it.
    """
    declared = {RUNTIME: {"users": READ_WRITE, "legacy_policy_mappings": READ}}
    bad = _fixture_privileges("bad_effective_privileges.json")
    good = _fixture_privileges("good_effective_privileges.json")

    assert verification_failures(
        declared, lambda role, table, privilege: (role, table, privilege) in bad
    ) == [PrivilegeEntry(RUNTIME, "legacy_policy_mappings", "SELECT")]
    assert (
        verification_failures(
            declared, lambda role, table, privilege: (role, table, privilege) in good
        )
        == []
    )


PERSISTENT_ENVIRONMENT = {
    "V2_MIGRATION_DATABASE_URL": (
        "postgresql+psycopg://policyengine_v2_migrator:secret-value@"
        "db.abcdefghijklmnopqrst.supabase.co:5432/postgres?sslmode=require"
    ),
    "V2_SUPABASE_PROJECT_REF": "abcdefghijklmnopqrst",
    "V2_SUPABASE_ENVIRONMENT": "staging",
    "DEPLOYMENT_ENVIRONMENT": "staging",
}


def _engine_never_built(_settings: object) -> object:
    msg = "the command must stop before connecting"
    raise AssertionError(msg)


def test_creating_roles_is_refused_for_a_persistent_database() -> None:
    with pytest.raises(
        privilege_reconciliation.V2ConfigurationError, match="disposable"
    ):
        privilege_reconciliation.run(
            "apply",
            create_roles=True,
            environ=PERSISTENT_ENVIRONMENT,
            engine_builder=_engine_never_built,
        )


@pytest.mark.parametrize("environment", ["", "test", "prod"])
def test_a_persistent_database_needs_staging_or_production(environment: str) -> None:
    with pytest.raises(
        privilege_reconciliation.V2ConfigurationError, match="DEPLOYMENT_ENVIRONMENT"
    ):
        privilege_reconciliation.run(
            "verify",
            environ=PERSISTENT_ENVIRONMENT | {"DEPLOYMENT_ENVIRONMENT": environment},
            engine_builder=_engine_never_built,
        )


def test_configuration_errors_exit_with_status_two_without_the_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in PERSISTENT_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "test")

    status = privilege_reconciliation.main(["verify"])

    captured = capsys.readouterr()
    assert status == 2
    assert "DEPLOYMENT_ENVIRONMENT" in captured.err
    assert "secret-value" not in captured.err + captured.out
