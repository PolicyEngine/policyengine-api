"""PostgreSQL tests for granting and checking the declared v2 table privileges.

``scripts/reconcile_v2_privileges.py`` runs these operations after every v2
schema upgrade (rule ``api.v2.deployed-privileges-match``). Tests that need a
privilege to be missing or extra use their own temporary roles, so the managed
roles other integration tests run as keep exactly their declared privileges.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from policyengine_api.data.v2 import privilege_reconciliation
from policyengine_api.data.v2.migration_target import V2_ALEMBIC_DISPOSABLE_TEST
from policyengine_api.data.v2.models import Region
from policyengine_api.data.v2.privilege_reconciliation import (
    DEPLOYMENT_ENVIRONMENT,
    DefaultPrivilege,
    PrivilegeEntry,
    apply_declared_privileges,
    check_declared_privileges,
    check_table_wide_overrides,
    read_default_privileges,
    read_granted_column_privileges,
    read_granted_privileges,
    run,
    skipped_roles,
)
from policyengine_api.data.v2.privileges import READ, TablePrivilege, update_columns
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from tests.fixtures.database_sessions import act_as, create_role, drop_role, grant
from tests.integration.catalog_privilege_objects import (
    PUBLIC_GRANTEE,
    SCHEMA,
    PrivilegeTestMaterializedView,
    PrivilegeTestView,
    alter_default_privileges,
    create_sequence,
    create_view,
    grant_on_schema_object,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session


@pytest.fixture
def temporary_role(v2_owner_sessions) -> Iterator[Callable[[], str]]:
    """Return a builder of NOLOGIN roles that are dropped after the test."""
    created_roles: list[str] = []

    def create_temporary_role() -> str:
        role = f"policyengine_privilege_test_{uuid4().hex[:12]}"
        with v2_owner_sessions.begin() as session:
            create_role(session, role)
        created_roles.append(role)
        return role

    try:
        yield create_temporary_role
    finally:
        with v2_owner_sessions.begin() as session:
            for role in created_roles:
                drop_role(session, role)


def _has_privilege(
    sessions: sessionmaker[Session], role: str, table: str, privilege: str
) -> bool:
    with sessions() as session:
        return bool(
            session.execute(
                select(func.has_table_privilege(role, f"public.{table}", privilege))
            ).scalar_one()
        )


def _has_column_privilege(
    sessions: sessionmaker[Session],
    role: str,
    table: str,
    column: str,
    privilege: str,
) -> bool:
    with sessions() as session:
        return bool(
            session.execute(
                select(
                    func.has_column_privilege(
                        role, f"public.{table}", column, privilege
                    )
                )
            ).scalar_one()
        )


def test_apply_grants_declared_columns_alone_and_verify_checks_them(
    v2_owner_sessions, temporary_role
) -> None:
    role = temporary_role()
    declared = {role: {"regions": READ | {update_columns("label")}}}
    with v2_owner_sessions.begin() as session:
        first_plan, _defaults = apply_declared_privileges(session, declared)
    with v2_owner_sessions.begin() as session:
        second_plan, _defaults = apply_declared_privileges(session, declared)
        missing = check_declared_privileges(session, declared)
        overrides = check_table_wide_overrides(session, declared)

    assert first_plan.grants == (
        PrivilegeEntry(role, "regions", "SELECT"),
        PrivilegeEntry(role, "regions", "UPDATE", column="label"),
    )
    assert (second_plan.grants, second_plan.undeclared) == ((), ())
    assert (missing, overrides) == ([], [])
    assert _has_column_privilege(v2_owner_sessions, role, "regions", "label", "UPDATE")
    assert not _has_column_privilege(
        v2_owner_sessions, role, "regions", "code", "UPDATE"
    )
    assert not _has_privilege(v2_owner_sessions, role, "regions", "UPDATE")


def test_verify_fails_when_a_role_can_update_the_whole_table(
    disposable_v2_database_url, v2_owner_sessions, temporary_role, monkeypatch, tmp_path
) -> None:
    """``UPDATE`` on the whole table would let the role change every column."""
    role = temporary_role()
    monkeypatch.setattr(
        privilege_reconciliation,
        "declared_privileges",
        lambda _environment: {role: {"regions": READ | {update_columns("label")}}},
    )
    monkeypatch.setattr(
        privilege_reconciliation, "ROLES_AWAITING_PROVISIONING", frozenset()
    )
    summary_path = tmp_path / "summary.md"
    environ = {
        V2_MIGRATION_DATABASE_URL: disposable_v2_database_url,
        V2_ALEMBIC_DISPOSABLE_TEST: "1",
        DEPLOYMENT_ENVIRONMENT: "test",
        "GITHUB_STEP_SUMMARY": str(summary_path),
    }

    apply_status = run("apply", environ=environ)
    with v2_owner_sessions.begin() as session:
        grant(session, "UPDATE", on=Region, to=role)
    verify_status = run("verify", environ=environ)
    summary = summary_path.read_text(encoding="utf-8")

    assert (apply_status, verify_status) == (0, 1)
    assert (
        f"`{role}` holds UPDATE on the whole of `regions`, which overrides its "
        "declared columns"
    ) in summary


def test_apply_revokes_a_new_tables_whole_table_update_and_verify_passes(
    disposable_v2_database_url, v2_owner_sessions, temporary_role, monkeypatch, tmp_path
) -> None:
    """A new table's default privileges give UPDATE on the whole table.

    The role starts as staging's runtime role did on ``user_type_changes``:
    the whole-table privileges, the declared column grant an earlier ``apply``
    made, and an undeclared column grant. ``apply`` revokes the whole-table
    ``UPDATE``, which removes both column grants, and grants the declared one
    again in the same transaction, so ``verify`` passes. The extra ``INSERT``
    and ``DELETE`` stay, reported but not revoked.
    """
    role = temporary_role()
    declared = {role: {"regions": READ | {update_columns("label")}}}
    monkeypatch.setattr(
        privilege_reconciliation, "declared_privileges", lambda _environment: declared
    )
    monkeypatch.setattr(
        privilege_reconciliation, "ROLES_AWAITING_PROVISIONING", frozenset()
    )
    with v2_owner_sessions.begin() as session:
        grant(session, "SELECT, INSERT, UPDATE, DELETE", on=Region, to=role)
        grant(session, "UPDATE (label, code)", on=Region, to=role)
    summary_path = tmp_path / "summary.md"
    environ = {
        V2_MIGRATION_DATABASE_URL: disposable_v2_database_url,
        V2_ALEMBIC_DISPOSABLE_TEST: "1",
        DEPLOYMENT_ENVIRONMENT: "test",
        "GITHUB_STEP_SUMMARY": str(summary_path),
    }

    apply_status = run("apply", environ=environ)
    verify_status = run("verify", environ=environ)
    summary = summary_path.read_text(encoding="utf-8")
    with v2_owner_sessions.begin() as session:
        second_plan, _defaults = apply_declared_privileges(session, declared)

    assert (apply_status, verify_status) == (0, 0)
    assert f"| `{role}` | `regions` | UPDATE, UPDATE (code) |" in summary
    assert f"| `{role}` | `regions` | UPDATE (label) |" in summary
    assert f"| `{role}` | `regions` | DELETE, INSERT |" in summary
    assert not _has_privilege(v2_owner_sessions, role, "regions", "UPDATE")
    assert _has_column_privilege(v2_owner_sessions, role, "regions", "label", "UPDATE")
    assert not _has_column_privilege(
        v2_owner_sessions, role, "regions", "code", "UPDATE"
    )
    assert _has_privilege(v2_owner_sessions, role, "regions", "DELETE")
    assert (second_plan.revocations, second_plan.grants) == ((), ())


def test_apply_grants_nothing_the_second_time_and_verify_passes(
    disposable_v2_database_url, managed_v2_roles, capsys
) -> None:
    environ = {
        V2_MIGRATION_DATABASE_URL: disposable_v2_database_url,
        V2_ALEMBIC_DISPOSABLE_TEST: "1",
        DEPLOYMENT_ENVIRONMENT: managed_v2_roles.deployment_environment,
    }

    first_apply_status = run("apply", environ=environ)
    capsys.readouterr()
    second_apply_status = run("apply", environ=environ)
    second_apply_report = capsys.readouterr().out
    verify_status = run("verify", environ=environ)
    verify_output = capsys.readouterr().out

    assert (first_apply_status, second_apply_status, verify_status) == (0, 0, 0)
    assert "Nothing: every declared privilege was already granted." in (
        second_apply_report
    )
    assert "Every declared v2 table privilege is held" in verify_output
    assert disposable_v2_database_url not in second_apply_report + verify_output


def test_apply_reports_an_extra_privilege_and_does_not_revoke_it(
    v2_owner_sessions, temporary_role
) -> None:
    role = temporary_role()
    declared = {role: {"regions": READ}}
    with v2_owner_sessions.begin() as session:
        first_plan, _defaults = apply_declared_privileges(session, declared)
        grant(session, "DELETE", on=Region, to=role)
    with v2_owner_sessions.begin() as session:
        second_plan, _defaults = apply_declared_privileges(session, declared)
        missing_after_apply = check_declared_privileges(session, declared)

    assert first_plan.grants == (PrivilegeEntry(role, "regions", "SELECT"),)
    assert second_plan.grants == ()
    assert second_plan.undeclared == (PrivilegeEntry(role, "regions", "DELETE"),)
    assert missing_after_apply == []
    assert _has_privilege(v2_owner_sessions, role, "regions", "DELETE")


def test_a_missing_role_blocks_every_grant_and_fails_verification(
    v2_owner_sessions, temporary_role
) -> None:
    role = temporary_role()
    absent_role = f"policyengine_privilege_test_absent_{uuid4().hex[:12]}"
    declared = {
        role: {"regions": READ},
        absent_role: {"regions": frozenset({TablePrivilege.SELECT})},
    }
    with v2_owner_sessions.begin() as session:
        plan, _defaults = apply_declared_privileges(session, declared)
        missing = check_declared_privileges(session, declared)

    assert not plan.can_apply
    assert plan.missing_roles == (absent_role,)
    assert not _has_privilege(v2_owner_sessions, role, "regions", "SELECT")
    assert missing == sorted(
        [
            PrivilegeEntry(absent_role, "regions", "SELECT"),
            PrivilegeEntry(role, "regions", "SELECT"),
        ]
    )


def test_a_role_awaiting_creation_is_skipped_until_it_exists(
    v2_owner_sessions, temporary_role
) -> None:
    role = temporary_role()
    absent_role = f"policyengine_privilege_test_absent_{uuid4().hex[:12]}"
    declared = {role: {"regions": READ}, absent_role: {"regions": READ}}
    with v2_owner_sessions.begin() as session:
        plan, _defaults = apply_declared_privileges(
            session, declared, roles_awaiting_creation={absent_role}
        )
        skipped = skipped_roles(session, declared, {absent_role})
        missing = check_declared_privileges(
            session,
            {name: tables for name, tables in declared.items() if name not in skipped},
        )

    assert plan.can_apply
    assert plan.skipped_roles == (absent_role,)
    assert plan.grants == (PrivilegeEntry(role, "regions", "SELECT"),)
    assert skipped == (absent_role,)
    assert missing == []
    assert _has_privilege(v2_owner_sessions, role, "regions", "SELECT")


def test_the_deploy_steps_pass_and_name_a_role_awaiting_creation(
    disposable_v2_database_url, temporary_role, monkeypatch, capsys, tmp_path
) -> None:
    """``apply`` and ``verify`` succeed while a role awaiting creation is absent."""
    role = temporary_role()
    absent_role = f"policyengine_privilege_test_absent_{uuid4().hex[:12]}"
    monkeypatch.setattr(
        privilege_reconciliation,
        "declared_privileges",
        lambda _environment: {role: {"regions": READ}, absent_role: {"regions": READ}},
    )
    monkeypatch.setattr(
        privilege_reconciliation,
        "ROLES_AWAITING_PROVISIONING",
        frozenset({absent_role}),
    )
    summary_path = tmp_path / "summary.md"
    environ = {
        V2_MIGRATION_DATABASE_URL: disposable_v2_database_url,
        V2_ALEMBIC_DISPOSABLE_TEST: "1",
        DEPLOYMENT_ENVIRONMENT: "test",
        "GITHUB_STEP_SUMMARY": str(summary_path),
    }

    apply_status = run("apply", environ=environ)
    apply_report = capsys.readouterr().out
    verify_status = run("verify", environ=environ)
    verify_output = capsys.readouterr().out

    assert (apply_status, verify_status) == (0, 0)
    assert f"`{absent_role}`" in apply_report
    assert absent_role in verify_output
    assert "Every other declared v2 table privilege is held." in verify_output
    assert "Every declared v2 table privilege is held" not in verify_output
    # Each step names the skipped role in the job summary.
    assert summary_path.read_text(encoding="utf-8").count(f"`{absent_role}`") == 2


def test_verify_fails_once_a_role_awaiting_creation_exists_without_its_privileges(
    disposable_v2_database_url, temporary_role, monkeypatch, capsys, tmp_path
) -> None:
    """A role awaiting creation is checked as soon as it exists."""
    role = temporary_role()
    absent_role = f"policyengine_privilege_test_absent_{uuid4().hex[:12]}"
    monkeypatch.setattr(
        privilege_reconciliation,
        "declared_privileges",
        lambda _environment: {role: {"regions": READ}, absent_role: {"regions": READ}},
    )
    monkeypatch.setattr(
        privilege_reconciliation,
        "ROLES_AWAITING_PROVISIONING",
        frozenset({role, absent_role}),
    )
    summary_path = tmp_path / "summary.md"
    environ = {
        V2_MIGRATION_DATABASE_URL: disposable_v2_database_url,
        V2_ALEMBIC_DISPOSABLE_TEST: "1",
        DEPLOYMENT_ENVIRONMENT: "test",
        "GITHUB_STEP_SUMMARY": str(summary_path),
    }

    verify_status = run("verify", environ=environ)
    capsys.readouterr()
    summary = summary_path.read_text(encoding="utf-8")

    assert verify_status == 1
    assert f"`{role}` lacks SELECT on `regions`" in summary
    assert (
        "Declared roles not created yet, skipped until an operator creates them: "
        f"`{absent_role}`"
    ) in summary
    assert summary.count("## v2 table privileges") == 1


def test_default_privileges_are_read_for_tables_and_sequences_including_public(
    v2_owner_sessions: sessionmaker[Session],
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
    temporary_role: Callable[[], str],
) -> None:
    """Each default privilege is read with its creating role, schema and grantee.

    A default privilege given to PUBLIC names no grantee role, so it is read
    only for its creating role.
    """
    creator = temporary_role()
    reader = temporary_role()
    with v2_owner_sessions.begin() as session:
        alter_default_privileges(
            session,
            creating_role=creator,
            privileges="SELECT",
            object_type="TABLES",
            to=reader,
        )
        alter_default_privileges(
            session,
            creating_role=creator,
            privileges="USAGE",
            object_type="SEQUENCES",
            to=PUBLIC_GRANTEE,
        )

    with v2_sessions_as_role(creator)() as session:
        for_both_roles = read_default_privileges(session, [creator, reader])
        for_the_reader = read_default_privileges(session, [reader])

    readers_tables = DefaultPrivilege(
        creating_role=creator,
        schema=SCHEMA,
        object_type="tables",
        grantee=reader,
        privileges=("SELECT",),
    )
    assert for_both_roles == [
        DefaultPrivilege(
            creating_role=creator,
            schema=SCHEMA,
            object_type="sequences",
            grantee=PUBLIC_GRANTEE,
            privileges=("USAGE",),
        ),
        readers_tables,
    ]
    assert for_the_reader == [readers_tables]


def test_grants_on_sequences_views_and_materialized_views_are_read(
    v2_owner_sessions: sessionmaker[Session],
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
    temporary_role: Callable[[], str],
) -> None:
    """The reads return each grant a role holds, on whole relations and columns.

    A temporary role creates the objects and reads the grants, as the migration
    role owns the tables and runs the reconciliation.
    """
    creator = temporary_role()
    reader = temporary_role()
    sequence = f"privilege_test_sequence_{uuid4().hex[:12]}"
    view = PrivilegeTestView.__tablename__
    materialized_view = PrivilegeTestMaterializedView.__tablename__
    with v2_owner_sessions.begin() as session:
        grant_on_schema_object(
            session, "CREATE", object_kind="SCHEMA", name=SCHEMA, to=creator
        )
        act_as(session, creator)
        create_sequence(session, sequence)
        create_view(session, PrivilegeTestView)
        create_view(session, PrivilegeTestMaterializedView)
        grant_on_schema_object(
            session, "USAGE, SELECT", object_kind="SEQUENCE", name=sequence, to=reader
        )
        grant(session, "SELECT", on=PrivilegeTestView, to=reader)
        grant(session, "UPDATE (label)", on=PrivilegeTestView, to=reader)
        grant(session, "SELECT", on=PrivilegeTestMaterializedView, to=reader)
        grant(session, "SELECT (label)", on=PrivilegeTestMaterializedView, to=reader)

    with v2_sessions_as_role(creator)() as session:
        granted = read_granted_privileges(session, [reader])
        granted_columns = read_granted_column_privileges(session, [reader])

    assert granted == {
        reader: {
            sequence: {"SELECT", "USAGE"},
            view: {"SELECT"},
            materialized_view: {"SELECT"},
        }
    }
    assert granted_columns == {
        reader: {
            view: {"label": {"UPDATE"}},
            materialized_view: {"label": {"SELECT"}},
        }
    }
