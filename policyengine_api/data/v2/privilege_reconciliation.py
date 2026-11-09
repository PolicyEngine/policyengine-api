"""Grant and check the table privileges the v2 manifest declares.

``scripts/reconcile_v2_privileges.py`` runs this after every v2 schema upgrade,
connected as the migration role, which owns every table and so may grant on
it. Two modes:

- ``apply`` reads the managed roles' current grants, on whole tables and on
  columns, grants every declared privilege a role lacks, and reports privileges
  the manifest doesn't declare. It never revokes, and it changes nothing when a
  declared role or table is missing. Running it again grants nothing more.
- ``verify`` checks every declared privilege with ``has_table_privilege``, or
  ``has_column_privilege`` for each column of a column privilege (rule
  ``api.v2.deployed-privileges-match``), and fails on any that is missing. It
  also fails when a role holds on the whole table a privilege the manifest
  declares for only some of its columns, since that lets the role use it on
  every column.

Both skip a missing role the manifest lists in ``ROLES_AWAITING_PROVISIONING``,
and name it in their output, so a pull request can declare a role before an
operator creates it. Once the role exists, ``apply`` grants its privileges and
``verify`` checks them.

``--create-missing-roles`` creates the managed roles as ``NOLOGIN`` roles. It
is refused unless the target is the disposable test database
(``V2_ALEMBIC_DISPOSABLE_TEST=1``); in staging and production the roles are
provisioned outside the repository.

The report goes to stdout and, when set, ``GITHUB_STEP_SUMMARY``. It names roles,
tables and privileges only, never a connection URL or credential.

This module reads the database and runs the commands; ``privilege_plans``
compares, states and reports the privileges, and its names are re-exported here.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import bindparam, text
from sqlalchemy.pool import NullPool
from sqlmodel import create_engine

from policyengine_api.data.v2.migration_target import (
    V2AlembicSettings,
    load_v2_alembic_settings,
    qualify_v2_connection,
)
from policyengine_api.data.v2.privilege_plans import (
    SCHEMA,
    DefaultPrivilege,
    GrantedPrivileges,
    PrivilegeEntry,
    PrivilegeReconciliationError,
    ReconciliationPlan,
    UnsafeIdentifierError,
    grant_statements,
    plan_reconciliation,
    render_summary,
    safe_identifier,
    skipped_roles_line,
    table_wide_overrides,
    verification_failures,
    verification_report,
)
from policyengine_api.data.v2.privileges import (
    PERSISTENT_ENVIRONMENTS,
    ROLES_AWAITING_PROVISIONING,
    DeclaredPrivilege,
    declared_privileges,
)
from policyengine_api.data.v2.settings import V2ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

    from sqlalchemy import Connection, Engine

# Names other modules import from here; the planning and reporting half lives
# in privilege_plans.
__all__ = [
    "DEPLOYMENT_ENVIRONMENT",
    "GITHUB_STEP_SUMMARY",
    "SCHEMA",
    "DefaultPrivilege",
    "GrantedPrivileges",
    "PrivilegeEntry",
    "PrivilegeReconciliationError",
    "ReconciliationPlan",
    "UnsafeIdentifierError",
    "apply_declared_privileges",
    "check_declared_privileges",
    "check_table_wide_overrides",
    "create_missing_roles",
    "grant_statements",
    "main",
    "plan_reconciliation",
    "read_default_privileges",
    "read_existing_roles",
    "read_granted_column_privileges",
    "read_granted_privileges",
    "read_public_tables",
    "render_summary",
    "run",
    "skipped_roles",
    "table_wide_overrides",
    "verification_failures",
]

DEPLOYMENT_ENVIRONMENT = "DEPLOYMENT_ENVIRONMENT"
GITHUB_STEP_SUMMARY = "GITHUB_STEP_SUMMARY"


# --- Database access -------------------------------------------------------

_GRANTED_PRIVILEGES = text(
    """
    SELECT grantee_role.rolname AS role_name,
           table_class.relname AS table_name,
           acl_entry.privilege_type AS privilege
    FROM pg_class AS table_class
    JOIN pg_namespace AS table_namespace
      ON table_namespace.oid = table_class.relnamespace
    CROSS JOIN LATERAL aclexplode(table_class.relacl) AS acl_entry
    JOIN pg_roles AS grantee_role ON grantee_role.oid = acl_entry.grantee
    WHERE table_namespace.nspname = :schema
      AND table_class.relkind IN ('r', 'p', 'S', 'v', 'm')
      AND grantee_role.rolname IN :roles
    """
).bindparams(bindparam("roles", expanding=True))

_EXISTING_ROLES = text(
    "SELECT rolname FROM pg_roles WHERE rolname IN :roles"
).bindparams(bindparam("roles", expanding=True))

_PUBLIC_TABLES = text(
    """
    SELECT table_class.relname
    FROM pg_class AS table_class
    JOIN pg_namespace AS table_namespace
      ON table_namespace.oid = table_class.relnamespace
    WHERE table_namespace.nspname = :schema AND table_class.relkind IN ('r', 'p')
    """
)

_DEFAULT_PRIVILEGES = text(
    """
    SELECT pg_get_userbyid(default_acl.defaclrole) AS creating_role,
           coalesce(acl_namespace.nspname, '') AS schema_name,
           CASE default_acl.defaclobjtype
             WHEN 'r' THEN 'tables' WHEN 'S' THEN 'sequences'
             WHEN 'f' THEN 'functions' WHEN 'T' THEN 'types'
             WHEN 'n' THEN 'schemas' ELSE default_acl.defaclobjtype::text
           END AS object_type,
           coalesce(grantee_role.rolname, 'PUBLIC') AS grantee,
           acl_entry.privilege_type AS privilege
    FROM pg_default_acl AS default_acl
    LEFT JOIN pg_namespace AS acl_namespace
      ON acl_namespace.oid = default_acl.defaclnamespace
    CROSS JOIN LATERAL aclexplode(default_acl.defaclacl) AS acl_entry
    LEFT JOIN pg_roles AS grantee_role ON grantee_role.oid = acl_entry.grantee
    WHERE coalesce(grantee_role.rolname, '') IN :roles
       OR pg_get_userbyid(default_acl.defaclrole) IN :roles
    """
).bindparams(bindparam("roles", expanding=True))

_GRANTED_COLUMN_PRIVILEGES = text(
    """
    SELECT grantee_role.rolname AS role_name,
           table_class.relname AS table_name,
           table_column.attname AS column_name,
           acl_entry.privilege_type AS privilege
    FROM pg_attribute AS table_column
    JOIN pg_class AS table_class ON table_class.oid = table_column.attrelid
    JOIN pg_namespace AS table_namespace
      ON table_namespace.oid = table_class.relnamespace
    CROSS JOIN LATERAL aclexplode(table_column.attacl) AS acl_entry
    JOIN pg_roles AS grantee_role ON grantee_role.oid = acl_entry.grantee
    WHERE table_namespace.nspname = :schema
      AND table_class.relkind IN ('r', 'p', 'v', 'm')
      AND table_column.attnum > 0
      AND NOT table_column.attisdropped
      AND grantee_role.rolname IN :roles
    """
).bindparams(bindparam("roles", expanding=True))

_HAS_TABLE_PRIVILEGE = text(
    "SELECT has_table_privilege(:role, :qualified_table, :privilege)"
)

_HAS_COLUMN_PRIVILEGE = text(
    "SELECT has_column_privilege(:role, :qualified_table, :column, :privilege)"
)


def read_existing_roles(connection: Connection, roles: Collection[str]) -> set[str]:
    """Return which of ``roles`` exist."""
    return set(connection.execute(_EXISTING_ROLES, {"roles": list(roles)}).scalars())


def read_public_tables(connection: Connection) -> set[str]:
    """Return every table in the public schema."""
    return set(connection.execute(_PUBLIC_TABLES, {"schema": SCHEMA}).scalars())


def read_granted_privileges(
    connection: Connection, roles: Collection[str]
) -> dict[str, dict[str, set[str]]]:
    """Return the roles' direct grants on public tables, views and sequences."""
    granted: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in connection.execute(
        _GRANTED_PRIVILEGES, {"schema": SCHEMA, "roles": list(roles)}
    ):
        granted[row.role_name][row.table_name].add(row.privilege)
    return {role: dict(tables) for role, tables in granted.items()}


def read_granted_column_privileges(
    connection: Connection, roles: Collection[str]
) -> dict[str, dict[str, dict[str, set[str]]]]:
    """Return the roles' direct grants on columns of public tables and views."""
    granted: dict[str, dict[str, dict[str, set[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(set))
    )
    for row in connection.execute(
        _GRANTED_COLUMN_PRIVILEGES, {"schema": SCHEMA, "roles": list(roles)}
    ):
        granted[row.role_name][row.table_name][row.column_name].add(row.privilege)
    return {
        role: {table: dict(columns) for table, columns in tables.items()}
        for role, tables in granted.items()
    }


def read_default_privileges(
    connection: Connection, roles: Collection[str]
) -> list[DefaultPrivilege]:
    """Return default privileges that involve the managed roles."""
    grouped: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for row in connection.execute(_DEFAULT_PRIVILEGES, {"roles": list(roles)}):
        grouped[(row.creating_role, row.schema_name, row.object_type, row.grantee)].add(
            row.privilege
        )
    return [
        DefaultPrivilege(
            creating_role=creating_role,
            schema=schema,
            object_type=object_type,
            grantee=grantee,
            privileges=tuple(sorted(privileges)),
        )
        for (creating_role, schema, object_type, grantee), privileges in sorted(
            grouped.items()
        )
    ]


def create_missing_roles(connection: Connection, roles: Iterable[str]) -> list[str]:
    """Create each missing role as NOLOGIN; only for the disposable test database."""
    missing = sorted(set(roles) - read_existing_roles(connection, list(roles)))
    quote = connection.dialect.identifier_preparer.quote
    for role in missing:
        connection.execute(text(f"CREATE ROLE {quote(safe_identifier(role))} NOLOGIN"))
    return missing


def apply_declared_privileges(
    connection: Connection,
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
    *,
    roles_awaiting_creation: Collection[str] = (),
) -> tuple[ReconciliationPlan, list[DefaultPrivilege]]:
    """Grant every declared privilege a role lacks; never revoke.

    Grants nothing when a declared role or table is missing, unless the missing
    role awaits creation, which is skipped.
    """
    roles = list(declared)
    plan = plan_reconciliation(
        declared,
        GrantedPrivileges(
            tables=read_granted_privileges(connection, roles),
            columns=read_granted_column_privileges(connection, roles),
        ),
        existing_roles=read_existing_roles(connection, roles),
        existing_tables=read_public_tables(connection),
        roles_awaiting_creation=roles_awaiting_creation,
    )
    if plan.can_apply:
        for statement in grant_statements(
            plan, connection.dialect.identifier_preparer.quote
        ):
            connection.execute(text(statement))
    return plan, read_default_privileges(connection, roles)


def skipped_roles(
    connection: Connection,
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
    roles_awaiting_creation: Collection[str],
) -> tuple[str, ...]:
    """Return the declared roles awaiting creation that don't exist yet."""
    existing_roles = read_existing_roles(connection, list(declared))
    return tuple(
        sorted((set(declared) & set(roles_awaiting_creation)) - existing_roles)
    )


def _privilege_checks(
    connection: Connection, roles: Collection[str]
) -> tuple[Callable[[str, str, str], bool], Callable[[str, str, str, str], bool]]:
    """Return checks of a role's effective table and column privileges.

    A missing role or table holds nothing.
    """
    existing_roles = read_existing_roles(connection, roles)
    existing_tables = read_public_tables(connection)

    def has_privilege(role: str, table: str, privilege: str) -> bool:
        if role not in existing_roles or table not in existing_tables:
            return False
        return bool(
            connection.execute(
                _HAS_TABLE_PRIVILEGE,
                {
                    "role": role,
                    "qualified_table": f"{SCHEMA}.{safe_identifier(table)}",
                    "privilege": privilege,
                },
            ).scalar_one()
        )

    def has_column_privilege(
        role: str, table: str, column: str, privilege: str
    ) -> bool:
        if role not in existing_roles or table not in existing_tables:
            return False
        return bool(
            connection.execute(
                _HAS_COLUMN_PRIVILEGE,
                {
                    "role": role,
                    "qualified_table": f"{SCHEMA}.{safe_identifier(table)}",
                    "column": safe_identifier(column),
                    "privilege": privilege,
                },
            ).scalar_one()
        )

    return has_privilege, has_column_privilege


def check_declared_privileges(
    connection: Connection,
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
) -> list[PrivilegeEntry]:
    """Return every declared privilege a role doesn't effectively hold.

    A missing role or table counts as missing every privilege declared for it;
    leave out the roles ``skipped_roles`` returns to skip them.
    """
    has_privilege, has_column_privilege = _privilege_checks(connection, list(declared))
    return verification_failures(declared, has_privilege, has_column_privilege)


def check_table_wide_overrides(
    connection: Connection,
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
) -> list[PrivilegeEntry]:
    """Return each column privilege a role also holds on the whole table."""
    has_privilege, _has_column_privilege = _privilege_checks(connection, list(declared))
    return table_wide_overrides(declared, has_privilege)


# --- Command-line interface -----------------------------------------------


def _deployment_environment(
    environ: Mapping[str, str], settings: V2AlembicSettings
) -> str:
    environment = environ.get(DEPLOYMENT_ENVIRONMENT, "").strip()
    if not environment:
        msg = f"{DEPLOYMENT_ENVIRONMENT} is required"
        raise V2ConfigurationError(msg)
    if not settings.disposable_test and environment not in PERSISTENT_ENVIRONMENTS:
        msg = (
            f"{DEPLOYMENT_ENVIRONMENT} must be staging or production for a "
            "persistent v2 database"
        )
        raise V2ConfigurationError(msg)
    return environment


def _write_summary(environ: Mapping[str, str], summary: str) -> None:
    print(summary)
    summary_path = environ.get(GITHUB_STEP_SUMMARY, "").strip()
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(summary)


def _verify(
    connection: Connection,
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
    roles_awaiting_creation: Collection[str],
    environment: str,
    environ: Mapping[str, str],
) -> int:
    """Check every declared privilege, skipping missing roles awaiting creation.

    A missing role in ``roles_awaiting_creation`` is skipped; any other missing
    role counts as missing every privilege declared for it. A role holding on a
    whole table a privilege declared for only some of its columns fails too.
    The roles skipped, the privileges missing and the whole-table privileges
    are written to stdout and the job summary under one heading.
    """
    skipped = skipped_roles(connection, declared, roles_awaiting_creation)
    checked = {role: tables for role, tables in declared.items() if role not in skipped}
    failures = check_declared_privileges(connection, checked)
    overrides = check_table_wide_overrides(connection, checked)
    heading = f"## v2 table privileges ({environment})\n\n"
    skipped_note = f"{skipped_roles_line(skipped)}\n\n" if skipped else ""
    if failures or overrides:
        _write_summary(
            environ,
            f"{heading}{skipped_note}{verification_report(failures, overrides)}",
        )
        return 1
    if skipped:
        _write_summary(
            environ,
            f"{heading}{skipped_note}"
            "Every other declared v2 table privilege is held.\n",
        )
        return 0
    print(f"Every declared v2 table privilege is held ({environment}).")
    return 0


def _build_engine(settings: V2AlembicSettings) -> Engine:
    return create_engine(settings.url, poolclass=NullPool)


def run(
    mode: str,
    *,
    create_roles: bool = False,
    environ: Mapping[str, str] | None = None,
    engine_builder: Callable[[V2AlembicSettings], Engine] = _build_engine,
) -> int:
    """Run ``apply`` or ``verify`` against the configured v2 database."""
    values = os.environ if environ is None else environ
    settings = load_v2_alembic_settings(values)
    environment = _deployment_environment(values, settings)
    if create_roles and not settings.disposable_test:
        msg = "--create-missing-roles is only allowed for the disposable test database"
        raise V2ConfigurationError(msg)
    declared = declared_privileges(environment)
    awaiting = ROLES_AWAITING_PROVISIONING
    engine = engine_builder(settings)
    try:
        with engine.begin() as connection:
            qualify_v2_connection(connection, settings)
            if mode == "verify":
                return _verify(connection, declared, awaiting, environment, values)
            if create_roles:
                created = create_missing_roles(connection, declared)
                if created:
                    print("Created roles: " + ", ".join(created))
            plan, defaults = apply_declared_privileges(
                connection, declared, roles_awaiting_creation=awaiting
            )
            _write_summary(
                values,
                render_summary(
                    plan,
                    defaults,
                    deployment_environment=environment,
                    applied=plan.can_apply,
                ),
            )
            return 0 if plan.can_apply else 1
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the arguments and run; configuration errors exit with status 2."""
    parser = argparse.ArgumentParser(
        description="Grant or check the v2 table privileges the manifest declares."
    )
    parser.add_argument("mode", choices=("apply", "verify"))
    parser.add_argument(
        "--create-missing-roles",
        action="store_true",
        help="create the managed roles first (disposable test database only)",
    )
    arguments = parser.parse_args(argv)
    try:
        return run(arguments.mode, create_roles=arguments.create_missing_roles)
    except V2ConfigurationError as error:
        print(
            f"v2 privilege reconciliation is not configured: {error}", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
