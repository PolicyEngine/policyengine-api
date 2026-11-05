"""Planning, statements and reports for the v2 privilege reconcile script."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from policyengine_api.data.v2 import privilege_reconciliation
from policyengine_api.data.v2.privilege_reconciliation import (
    DefaultPrivilege,
    GrantedPrivileges,
    PrivilegeEntry,
    ReconciliationPlan,
    grant_statements,
    plan_reconciliation,
    render_summary,
    table_wide_overrides,
    verification_failures,
)
from policyengine_api.data.v2.privileges import (
    READ,
    READ_WRITE,
    TablePrivilege,
    update_columns,
)

PROJECT_ROOT = Path(__file__).parents[3]
PROOF_FIXTURES = PROJECT_ROOT / "rules/fixtures/api.v2.deployed-privileges-match"
RUNTIME = "policyengine_v2_runtime"
STAGE12 = "policyengine_stage12_staging"
WORKER = "policyengine_v2_modal_worker"
# The Modal worker may read a run and update two of its columns.
WORKER_DECLARED = {
    WORKER: {"simulation_runs": READ | {update_columns("status", "completed_at")}}
}


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


def test_missing_declared_privileges_become_grants() -> None:
    plan = plan_reconciliation(
        _declared(),
        granted=GrantedPrivileges({RUNTIME: {"users": {"SELECT", "INSERT"}}}),
        existing_roles={RUNTIME, STAGE12},
        existing_tables={"users", "legacy_policy_mappings", "reports"},
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
        granted=GrantedPrivileges(
            {
                RUNTIME: {
                    "users": {"SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"},
                    "legacy_policy_mappings": {"SELECT", "INSERT"},
                    "reports": {"SELECT"},
                },
                STAGE12: {"users": {"SELECT"}},
            }
        ),
        existing_roles={RUNTIME, STAGE12},
        existing_tables={"users", "legacy_policy_mappings", "reports"},
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
        granted=GrantedPrivileges({RUNTIME: {"scratch_table": {"SELECT"}}}),
        existing_roles={RUNTIME, STAGE12},
        existing_tables={"users", "legacy_policy_mappings", "reports", "scratch_table"},
    )

    assert PrivilegeEntry(RUNTIME, "scratch_table", "SELECT") in plan.undeclared


def test_missing_roles_and_tables_are_recorded_and_block_the_plan() -> None:
    plan = plan_reconciliation(
        _declared(),
        granted=GrantedPrivileges({}),
        existing_roles={RUNTIME},
        existing_tables={"users", "reports"},
    )

    assert plan.missing_roles == (STAGE12,)
    assert plan.missing_tables == ("legacy_policy_mappings",)
    assert not plan.can_apply
    # Nothing is granted on a missing table or to a missing role.
    assert all(
        entry.role != STAGE12 and entry.table != "legacy_policy_mappings"
        for entry in plan.grants
    )


def test_a_missing_role_awaiting_creation_is_skipped_without_blocking() -> None:
    plan = plan_reconciliation(
        _declared(),
        granted=GrantedPrivileges({}),
        existing_roles={RUNTIME},
        existing_tables={"users", "legacy_policy_mappings", "reports"},
        roles_awaiting_creation={STAGE12},
    )

    assert plan.can_apply
    assert plan.missing_roles == ()
    assert plan.skipped_roles == (STAGE12,)
    assert {entry.role for entry in plan.grants} == {RUNTIME}


def test_a_role_awaiting_creation_gets_its_privileges_once_it_exists() -> None:
    declared = {RUNTIME: {"users": READ}, STAGE12: {"users": READ}}

    plan = plan_reconciliation(
        declared,
        granted=GrantedPrivileges({}),
        existing_roles={RUNTIME, STAGE12},
        existing_tables={"users"},
        roles_awaiting_creation={STAGE12},
    )

    assert plan.skipped_roles == ()
    assert plan.grants == (
        PrivilegeEntry(STAGE12, "users", "SELECT"),
        PrivilegeEntry(RUNTIME, "users", "SELECT"),
    )


def test_a_missing_role_not_awaiting_creation_still_blocks_the_plan() -> None:
    plan = plan_reconciliation(
        _declared(),
        granted=GrantedPrivileges({}),
        existing_roles={RUNTIME},
        existing_tables={"users", "legacy_policy_mappings", "reports"},
        roles_awaiting_creation={"policyengine_v2_some_other_role"},
    )

    assert plan.missing_roles == (STAGE12,)
    assert plan.skipped_roles == ()
    assert not plan.can_apply


def test_summary_names_the_roles_skipped_until_an_operator_creates_them() -> None:
    plan = ReconciliationPlan(
        grants=(),
        undeclared=(),
        missing_roles=(),
        missing_tables=(),
        skipped_roles=(STAGE12,),
    )

    summary = render_summary(plan, (), deployment_environment="staging", applied=True)

    assert (
        "Declared roles not created yet, skipped until an operator creates them: "
        f"`{STAGE12}`"
    ) in summary


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


def test_missing_declared_column_privileges_become_column_grants() -> None:
    plan = plan_reconciliation(
        WORKER_DECLARED,
        granted=GrantedPrivileges(
            tables={WORKER: {"simulation_runs": {"SELECT"}}},
            columns={WORKER: {"simulation_runs": {"status": {"UPDATE"}}}},
        ),
        existing_roles={WORKER},
        existing_tables={"simulation_runs"},
    )

    assert plan.grants == (
        PrivilegeEntry(WORKER, "simulation_runs", "UPDATE", column="completed_at"),
    )
    assert plan.undeclared == ()


def test_column_and_whole_table_privileges_beyond_the_manifest_are_reported() -> None:
    plan = plan_reconciliation(
        WORKER_DECLARED,
        granted=GrantedPrivileges(
            tables={WORKER: {"simulation_runs": {"SELECT", "UPDATE"}}},
            columns={
                WORKER: {
                    "simulation_runs": {
                        "status": {"UPDATE"},
                        "completed_at": {"UPDATE"},
                        "simulation_id": {"UPDATE"},
                    }
                }
            },
        ),
        existing_roles={WORKER},
        existing_tables={"simulation_runs"},
    )

    assert plan.grants == ()
    assert plan.undeclared == (
        PrivilegeEntry(WORKER, "simulation_runs", "UPDATE"),
        PrivilegeEntry(WORKER, "simulation_runs", "UPDATE", column="simulation_id"),
    )


def test_grant_statements_grant_column_privileges_per_role_and_table() -> None:
    plan = ReconciliationPlan(
        grants=(
            PrivilegeEntry(WORKER, "simulation_runs", "SELECT"),
            PrivilegeEntry(WORKER, "simulation_runs", "UPDATE", column="status"),
            PrivilegeEntry(WORKER, "simulation_runs", "UPDATE", column="completed_at"),
        ),
        undeclared=(),
        missing_roles=(),
        missing_tables=(),
    )

    assert grant_statements(plan, _quote) == [
        'GRANT SELECT ON TABLE "public"."simulation_runs" '
        'TO "policyengine_v2_modal_worker"',
        'GRANT UPDATE ("completed_at", "status") ON TABLE "public"."simulation_runs" '
        'TO "policyengine_v2_modal_worker"',
    ]


def test_grant_statements_refuse_an_unsafe_column_name() -> None:
    plan = ReconciliationPlan(
        grants=(
            PrivilegeEntry(WORKER, "simulation_runs", "UPDATE", column='status"; --'),
        ),
        undeclared=(),
        missing_roles=(),
        missing_tables=(),
    )

    with pytest.raises(privilege_reconciliation.UnsafeIdentifierError):
        grant_statements(plan, _quote)


def test_verification_reports_each_declared_column_the_role_lacks() -> None:
    failures = verification_failures(
        WORKER_DECLARED,
        lambda role, table, privilege: privilege == "SELECT",
        has_column_privilege=lambda role, table, column, privilege: column == "status",
    )

    assert failures == [
        PrivilegeEntry(WORKER, "simulation_runs", "UPDATE", column="completed_at")
    ]


def test_column_privileges_need_a_column_check() -> None:
    with pytest.raises(ValueError, match="column"):
        verification_failures(WORKER_DECLARED, lambda role, table, privilege: True)


def test_a_whole_table_privilege_overrides_its_declared_columns() -> None:
    """``UPDATE`` on the whole table lets a role change every column."""

    def has_privilege(role: str, table: str, privilege: str) -> bool:
        return privilege in {"SELECT", "UPDATE"}

    assert table_wide_overrides(WORKER_DECLARED, has_privilege) == [
        PrivilegeEntry(WORKER, "simulation_runs", "UPDATE")
    ]
    assert (
        table_wide_overrides(
            WORKER_DECLARED, lambda role, table, privilege: privilege == "SELECT"
        )
        == []
    )


def test_summary_lists_column_grants_with_their_columns() -> None:
    plan = ReconciliationPlan(
        grants=(
            PrivilegeEntry(WORKER, "simulation_runs", "SELECT"),
            PrivilegeEntry(WORKER, "simulation_runs", "UPDATE", column="status"),
            PrivilegeEntry(WORKER, "simulation_runs", "UPDATE", column="completed_at"),
        ),
        undeclared=(
            PrivilegeEntry(WORKER, "simulation_runs", "UPDATE", column="year"),
        ),
        missing_roles=(),
        missing_tables=(),
    )

    summary = render_summary(plan, (), deployment_environment="staging", applied=True)

    assert (
        "| `policyengine_v2_modal_worker` | `simulation_runs` | "
        "SELECT, UPDATE (completed_at, status) |"
    ) in summary
    assert (
        "| `policyengine_v2_modal_worker` | `simulation_runs` | UPDATE (year) |"
    ) in summary


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
