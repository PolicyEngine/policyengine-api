"""Grant and check the table privileges the v2 manifest declares.

``scripts/reconcile_v2_privileges.py`` runs this after every v2 schema upgrade,
connected as the migration role, which owns every table and so may grant on
it. Two modes:

- ``apply`` reads the managed roles' current grants, grants every declared
  privilege a role lacks, and reports privileges the manifest doesn't declare.
  It never revokes, and it changes nothing when a declared role or table is
  missing. Running it again grants nothing more.
- ``verify`` checks every declared privilege with ``has_table_privilege``
  (rule ``api.v2.deployed-privileges-match``) and fails on any that is missing.

``--create-missing-roles`` creates the managed roles as ``NOLOGIN`` roles. It
is refused unless the target is the disposable test database
(``V2_ALEMBIC_DISPOSABLE_TEST=1``); in staging and production the roles are
provisioned outside the repository.

The report goes to stdout and, when set, ``GITHUB_STEP_SUMMARY``. It names roles,
tables and privileges only, never a connection URL or credential.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import bindparam, text
from sqlalchemy.pool import NullPool
from sqlmodel import create_engine

from policyengine_api.data.v2.migration_target import (
    V2AlembicSettings,
    load_v2_alembic_settings,
    qualify_v2_connection,
)
from policyengine_api.data.v2.privileges import (
    PERSISTENT_ENVIRONMENTS,
    TablePrivilege,
    declared_privileges,
)
from policyengine_api.data.v2.settings import V2ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

    from sqlalchemy import Connection, Engine

DEPLOYMENT_ENVIRONMENT = "DEPLOYMENT_ENVIRONMENT"
GITHUB_STEP_SUMMARY = "GITHUB_STEP_SUMMARY"
SCHEMA = "public"
SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

DeclaredPrivileges = "Mapping[str, Mapping[str, frozenset[TablePrivilege]]]"


class PrivilegeReconciliationError(RuntimeError):
    """Raised when privileges can't be reconciled or don't match the manifest."""


class UnsafeIdentifierError(PrivilegeReconciliationError):
    """Raised for a role or table name that isn't a plain lowercase identifier."""


@dataclass(frozen=True, order=True)
class PrivilegeEntry:
    """One privilege one role holds, or should hold, on one table."""

    role: str
    table: str
    privilege: str


@dataclass(frozen=True)
class DefaultPrivilege:
    """A default privilege PostgreSQL gives on objects a role creates later."""

    creating_role: str
    schema: str
    object_type: str
    grantee: str
    privileges: tuple[str, ...]


@dataclass(frozen=True)
class ReconciliationPlan:
    """What ``apply`` grants and reports for one database."""

    grants: tuple[PrivilegeEntry, ...]
    undeclared: tuple[PrivilegeEntry, ...]
    missing_roles: tuple[str, ...]
    missing_tables: tuple[str, ...]

    @property
    def can_apply(self) -> bool:
        """Whether every declared role and table exists, so grants may run."""
        return not self.missing_roles and not self.missing_tables


def plan_reconciliation(
    declared: Mapping[str, Mapping[str, frozenset[TablePrivilege]]],
    granted: Mapping[str, Mapping[str, Collection[str]]],
    *,
    existing_roles: Collection[str],
    existing_tables: Collection[str],
) -> ReconciliationPlan:
    """Compare declared privileges with what the database grants.

    ``granted`` holds the managed roles' direct grants, by role then table.
    """
    missing_roles = tuple(sorted(set(declared) - set(existing_roles)))
    declared_tables = {table for tables in declared.values() for table in tables}
    missing_tables = tuple(sorted(declared_tables - set(existing_tables)))
    grants = sorted(
        PrivilegeEntry(role, table, privilege.value)
        for role, tables in declared.items()
        if role not in missing_roles
        for table, privileges in tables.items()
        if table not in missing_tables
        for privilege in privileges
        if privilege.value not in granted.get(role, {}).get(table, ())
    )
    undeclared = sorted(
        PrivilegeEntry(role, table, privilege)
        for role, tables in granted.items()
        for table, privileges in tables.items()
        for privilege in privileges
        if privilege
        not in {
            declared_privilege.value
            for declared_privilege in declared.get(role, {}).get(table, frozenset())
        }
    )
    return ReconciliationPlan(
        grants=tuple(grants),
        undeclared=tuple(undeclared),
        missing_roles=missing_roles,
        missing_tables=missing_tables,
    )


def _safe(identifier: str) -> str:
    if SAFE_IDENTIFIER.fullmatch(identifier) is None:
        msg = f"refusing to use {identifier!r} as a role or table name"
        raise UnsafeIdentifierError(msg)
    return identifier


def grant_statements(
    plan: ReconciliationPlan, quote_identifier: Callable[[str], str]
) -> list[str]:
    """Return one GRANT per role and table, with its privileges in name order."""
    privileges_by_target: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in plan.grants:
        privileges_by_target[(_safe(entry.role), _safe(entry.table))].add(
            TablePrivilege(entry.privilege).value
        )
    return [
        f"GRANT {', '.join(sorted(privileges))} ON TABLE "
        f"{quote_identifier(SCHEMA)}.{quote_identifier(table)} "
        f"TO {quote_identifier(role)}"
        for (role, table), privileges in sorted(
            privileges_by_target.items(), key=lambda item: (item[0][0], item[0][1])
        )
    ]


def verification_failures(
    declared: Mapping[str, Mapping[str, frozenset[TablePrivilege]]],
    has_privilege: Callable[[str, str, str], bool],
) -> list[PrivilegeEntry]:
    """Return every declared privilege the role doesn't effectively hold."""
    return sorted(
        PrivilegeEntry(role, table, privilege.value)
        for role, tables in declared.items()
        for table, privileges in tables.items()
        for privilege in privileges
        if not has_privilege(role, table, privilege.value)
    )


def _privilege_rows(entries: Iterable[PrivilegeEntry]) -> list[str]:
    rows_by_target: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry in entries:
        rows_by_target[(entry.role, entry.table)].append(entry.privilege)
    return [
        f"| `{role}` | `{table}` | {', '.join(sorted(privileges))} |"
        for (role, table), privileges in sorted(rows_by_target.items())
    ]


def render_summary(
    plan: ReconciliationPlan,
    default_privileges: Sequence[DefaultPrivilege],
    *,
    deployment_environment: str,
    applied: bool,
) -> str:
    """Return the Markdown report for the job summary and the log."""
    lines = [f"## v2 table privileges ({deployment_environment})", ""]
    if plan.missing_roles:
        lines += [
            "Declared roles missing from the database (nothing was granted): "
            + ", ".join(f"`{role}`" for role in plan.missing_roles),
            "",
        ]
    if plan.missing_tables:
        lines += [
            "Declared tables missing from the database (nothing was granted): "
            + ", ".join(f"`{table}`" for table in plan.missing_tables),
            "",
        ]
    grant_heading = "Granted" if applied else "Would grant"
    lines += [f"### {grant_heading}", ""]
    if plan.grants:
        lines += ["| Role | Table | Privileges |", "| --- | --- | --- |"]
        lines += _privilege_rows(plan.grants)
    else:
        lines.append("Nothing: every declared privilege was already granted.")
    lines += [
        "",
        "### Privileges the manifest doesn't declare (reported, not revoked)",
        "",
    ]
    if plan.undeclared:
        lines += ["| Role | Table | Privileges |", "| --- | --- | --- |"]
        lines += _privilege_rows(plan.undeclared)
    else:
        lines.append("None.")
    lines += ["", "### Default privileges for new tables", ""]
    if default_privileges:
        lines += [
            "| Creating role | Schema | Objects | Grantee | Privileges |",
            "| --- | --- | --- | --- | --- |",
        ]
        lines += [
            f"| `{default.creating_role}` | `{default.schema}` | "
            f"{default.object_type} | `{default.grantee}` | "
            f"{', '.join(default.privileges)} |"
            for default in default_privileges
        ]
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


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

_HAS_TABLE_PRIVILEGE = text(
    "SELECT has_table_privilege(:role, :qualified_table, :privilege)"
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


def read_default_privileges(
    connection: Connection, roles: Collection[str]
) -> list[DefaultPrivilege]:
    """Return default privileges that involve the managed roles."""
    grouped: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for row in connection.execute(_DEFAULT_PRIVILEGES, {"roles": list(roles)}):
        grouped[
            (row.creating_role, row.schema_name, row.object_type, row.grantee)
        ].add(row.privilege)
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
        connection.execute(text(f"CREATE ROLE {quote(_safe(role))} NOLOGIN"))
    return missing


def apply_declared_privileges(
    connection: Connection,
    declared: Mapping[str, Mapping[str, frozenset[TablePrivilege]]],
) -> tuple[ReconciliationPlan, list[DefaultPrivilege]]:
    """Grant every declared privilege a role lacks; never revoke.

    Grants nothing when a declared role or table is missing.
    """
    roles = list(declared)
    plan = plan_reconciliation(
        declared,
        read_granted_privileges(connection, roles),
        existing_roles=read_existing_roles(connection, roles),
        existing_tables=read_public_tables(connection),
    )
    if plan.can_apply:
        for statement in grant_statements(
            plan, connection.dialect.identifier_preparer.quote
        ):
            connection.execute(text(statement))
    return plan, read_default_privileges(connection, roles)


def check_declared_privileges(
    connection: Connection,
    declared: Mapping[str, Mapping[str, frozenset[TablePrivilege]]],
) -> list[PrivilegeEntry]:
    """Return every declared privilege a role doesn't effectively hold.

    A missing role or table counts as missing every privilege declared for it.
    """
    existing_roles = read_existing_roles(connection, list(declared))
    existing_tables = read_public_tables(connection)

    def has_privilege(role: str, table: str, privilege: str) -> bool:
        if role not in existing_roles or table not in existing_tables:
            return False
        return bool(
            connection.execute(
                _HAS_TABLE_PRIVILEGE,
                {
                    "role": role,
                    "qualified_table": f"{SCHEMA}.{_safe(table)}",
                    "privilege": privilege,
                },
            ).scalar_one()
        )

    return verification_failures(declared, has_privilege)


# --- Command line ----------------------------------------------------------


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
        with open(summary_path, "a", encoding="utf-8") as summary_file:
            summary_file.write(summary)


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
    engine = engine_builder(settings)
    try:
        with engine.begin() as connection:
            qualify_v2_connection(connection, settings)
            if mode == "verify":
                failures = check_declared_privileges(connection, declared)
                if failures:
                    rows = "\n".join(
                        f"- `{failure.role}` lacks {failure.privilege} on "
                        f"`{failure.table}`"
                        for failure in failures
                    )
                    _write_summary(
                        values,
                        f"## v2 table privileges ({environment})\n\n"
                        f"Declared privileges missing after reconciling:\n\n{rows}\n",
                    )
                    return 1
                print(f"Every declared v2 table privilege is held ({environment}).")
                return 0
            if create_roles:
                created = create_missing_roles(connection, declared)
                if created:
                    print("Created roles: " + ", ".join(created))
            plan, defaults = apply_declared_privileges(connection, declared)
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
    """Parse the command line and run; configuration errors exit with status 2."""
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
        print(f"v2 privilege reconciliation is not configured: {error}", file=sys.stderr)
        return 2
