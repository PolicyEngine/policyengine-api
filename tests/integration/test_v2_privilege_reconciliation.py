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
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from policyengine_api.data.v2.migration_target import V2_ALEMBIC_DISPOSABLE_TEST
from policyengine_api.data.v2.privilege_reconciliation import (
    DEPLOYMENT_ENVIRONMENT,
    PrivilegeEntry,
    apply_declared_privileges,
    check_declared_privileges,
    run,
)
from policyengine_api.data.v2.privileges import READ, TablePrivilege
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy import Engine


@pytest.fixture
def superuser_engine(disposable_v2_database_url) -> Iterator[Engine]:
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def temporary_role(superuser_engine) -> Iterator[Callable[[], str]]:
    """Return a builder of NOLOGIN roles that are dropped after the test."""
    created_roles: list[str] = []

    def create_role() -> str:
        role = f"policyengine_privilege_test_{uuid4().hex[:12]}"
        with superuser_engine.begin() as connection:
            connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        created_roles.append(role)
        return role

    try:
        yield create_role
    finally:
        with superuser_engine.begin() as connection:
            for role in created_roles:
                connection.execute(text(f'DROP OWNED BY "{role}"'))
                connection.execute(text(f'DROP ROLE "{role}"'))


def _has_privilege(engine: Engine, role: str, table: str, privilege: str) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT has_table_privilege(:role, :table, :privilege)"),
                {"role": role, "table": f"public.{table}", "privilege": privilege},
            ).scalar_one()
        )


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
    superuser_engine, temporary_role
) -> None:
    role = temporary_role()
    declared = {role: {"regions": READ}}
    with superuser_engine.begin() as connection:
        first_plan, _defaults = apply_declared_privileges(connection, declared)
        connection.execute(text(f'GRANT DELETE ON TABLE public.regions TO "{role}"'))
    with superuser_engine.begin() as connection:
        second_plan, _defaults = apply_declared_privileges(connection, declared)
        missing_after_apply = check_declared_privileges(connection, declared)

    assert first_plan.grants == (PrivilegeEntry(role, "regions", "SELECT"),)
    assert second_plan.grants == ()
    assert second_plan.undeclared == (PrivilegeEntry(role, "regions", "DELETE"),)
    assert missing_after_apply == []
    assert _has_privilege(superuser_engine, role, "regions", "DELETE")


def test_a_missing_role_blocks_every_grant_and_fails_verification(
    superuser_engine, temporary_role
) -> None:
    role = temporary_role()
    absent_role = f"policyengine_privilege_test_absent_{uuid4().hex[:12]}"
    declared = {
        role: {"regions": READ},
        absent_role: {"regions": frozenset({TablePrivilege.SELECT})},
    }
    with superuser_engine.begin() as connection:
        plan, _defaults = apply_declared_privileges(connection, declared)
        missing = check_declared_privileges(connection, declared)

    assert not plan.can_apply
    assert plan.missing_roles == (absent_role,)
    assert not _has_privilege(superuser_engine, role, "regions", "SELECT")
    assert missing == sorted(
        [
            PrivilegeEntry(absent_role, "regions", "SELECT"),
            PrivilegeEntry(role, "regions", "SELECT"),
        ]
    )
