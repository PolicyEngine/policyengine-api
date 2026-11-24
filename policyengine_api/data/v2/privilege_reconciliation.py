"""Grant and check the table privileges the v2 manifest declares.

``scripts/reconcile_v2_privileges.py`` runs this after every v2 schema upgrade,
connected as the migration role, which owns every table and so may grant on
it. Two modes:

- ``apply`` reads the managed roles' current grants, on whole tables and on
  columns, grants every declared privilege a role lacks, and reports privileges
  the manifest doesn't declare. It revokes only a whole-table privilege the
  manifest declares for named columns only, such as the ``UPDATE`` a new
  table's default privileges give, which also removes the role's column grants
  of it, and then grants the declared columns again, in the same transaction.
  It changes nothing when a declared role or table is missing. Running it
  again changes nothing more.
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

from sqlalchemy import Text, case, cast, false, func, or_, select, text, true
from sqlmodel import col

from policyengine_api.data.v2.migration_target import (
    V2AlembicSettings,
    load_v2_alembic_settings,
    qualify_v2_target,
)
from policyengine_api.data.v2.postgres_system_catalog import (
    PgAttribute,
    PgClass,
    PgDefaultAcl,
    PgNamespace,
    PgRoles,
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
    revoke_statements,
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
    from contextlib import AbstractContextManager

    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.sql.selectable import LateralFromClause
    from sqlmodel import Session

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
    "revoke_statements",
    "run",
    "skipped_roles",
    "table_wide_overrides",
    "verification_failures",
]

DEPLOYMENT_ENVIRONMENT = "DEPLOYMENT_ENVIRONMENT"
GITHUB_STEP_SUMMARY = "GITHUB_STEP_SUMMARY"


# --- Database access -------------------------------------------------------

# The relkind of the objects whose grants are read: tables, partitioned tables,
# sequences, views and materialized views; for column grants, the same less
# sequences; and the objects that hold rows, tables and partitioned tables.
_GRANTABLE_RELATION_KINDS = ("r", "p", "S", "v", "m")
_COLUMN_RELATION_KINDS = ("r", "p", "v", "m")
_TABLE_RELATION_KINDS = ("r", "p")
# pg_default_acl's object type codes, named as ALTER DEFAULT PRIVILEGES names them.
_DEFAULT_ACL_OBJECT_TYPES = {
    "r": "tables",
    "S": "sequences",
    "f": "functions",
    "T": "types",
    "n": "schemas",
}
# The grantee aclexplode reports for a privilege granted to PUBLIC: no role.
_PUBLIC_GRANTEE = "PUBLIC"


def _acl_entries(access_control_list: object, name: str) -> LateralFromClause:
    """Return the entries of an access control list, one row each (``aclexplode``).

    Each row has the entry's ``grantee`` role oid and ``privilege_type``.
    """
    return (
        func.aclexplode(access_control_list)
        .table_valued("grantee", "privilege_type")
        .lateral(name)
    )


def _quote(session: Session) -> Callable[[str], str]:
    """Return the session's dialect's identifier quoting."""
    from policyengine_api.data.v2.database import v2_schema_inspector

    quote: Callable[[str], str] = v2_schema_inspector(
        session
    ).dialect.identifier_preparer.quote
    return quote


def read_existing_roles(session: Session, roles: Collection[str]) -> set[str]:
    """Return which of ``roles`` exist."""
    role_name = col(PgRoles.rolname)
    return set(session.scalars(select(role_name).where(role_name.in_(list(roles)))))


def read_public_tables(session: Session) -> set[str]:
    """Return every table in the public schema."""
    return set(
        session.scalars(
            select(col(PgClass.relname))
            .join(PgNamespace, col(PgNamespace.oid) == col(PgClass.relnamespace))
            .where(
                col(PgNamespace.nspname) == SCHEMA,
                col(PgClass.relkind).in_(_TABLE_RELATION_KINDS),
            )
        )
    )


def read_granted_privileges(
    session: Session, roles: Collection[str]
) -> dict[str, dict[str, set[str]]]:
    """Return the roles' direct grants on public tables, views and sequences."""
    acl_entry = _acl_entries(PgClass.relacl, "acl_entry")
    statement = (
        select(
            col(PgRoles.rolname).label("role_name"),
            col(PgClass.relname).label("table_name"),
            acl_entry.c.privilege_type.label("privilege"),
        )
        .join(PgNamespace, col(PgNamespace.oid) == col(PgClass.relnamespace))
        .join(acl_entry, true())
        .join(PgRoles, col(PgRoles.oid) == acl_entry.c.grantee)
        .where(
            col(PgNamespace.nspname) == SCHEMA,
            col(PgClass.relkind).in_(_GRANTABLE_RELATION_KINDS),
            col(PgRoles.rolname).in_(list(roles)),
        )
    )
    granted: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in session.execute(statement):
        granted[row.role_name][row.table_name].add(row.privilege)
    return {role: dict(tables) for role, tables in granted.items()}


def read_granted_column_privileges(
    session: Session, roles: Collection[str]
) -> dict[str, dict[str, dict[str, set[str]]]]:
    """Return the roles' direct grants on columns of public tables and views."""
    acl_entry = _acl_entries(PgAttribute.attacl, "acl_entry")
    statement = (
        select(
            col(PgRoles.rolname).label("role_name"),
            col(PgClass.relname).label("table_name"),
            col(PgAttribute.attname).label("column_name"),
            acl_entry.c.privilege_type.label("privilege"),
        )
        .select_from(PgAttribute)
        .join(PgClass, col(PgClass.oid) == col(PgAttribute.attrelid))
        .join(PgNamespace, col(PgNamespace.oid) == col(PgClass.relnamespace))
        .join(acl_entry, true())
        .join(PgRoles, col(PgRoles.oid) == acl_entry.c.grantee)
        .where(
            col(PgNamespace.nspname) == SCHEMA,
            col(PgClass.relkind).in_(_COLUMN_RELATION_KINDS),
            col(PgAttribute.attnum) > 0,
            col(PgAttribute.attisdropped).is_(false()),
            col(PgRoles.rolname).in_(list(roles)),
        )
    )
    granted: dict[str, dict[str, dict[str, set[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(set))
    )
    for row in session.execute(statement):
        granted[row.role_name][row.table_name][row.column_name].add(row.privilege)
    return {
        role: {table: dict(columns) for table, columns in tables.items()}
        for role, tables in granted.items()
    }


def read_default_privileges(
    session: Session, roles: Collection[str]
) -> list[DefaultPrivilege]:
    """Return default privileges that involve the managed roles."""
    acl_entry = _acl_entries(PgDefaultAcl.defaclacl, "acl_entry")
    creating_role = func.pg_get_userbyid(col(PgDefaultAcl.defaclrole))
    object_type_code = cast(col(PgDefaultAcl.defaclobjtype), Text)
    grantee_role_name = col(PgRoles.rolname)
    statement = (
        select(
            creating_role.label("creating_role"),
            func.coalesce(col(PgNamespace.nspname), "").label("schema_name"),
            case(
                _DEFAULT_ACL_OBJECT_TYPES,
                value=object_type_code,
                else_=object_type_code,
            ).label("object_type"),
            func.coalesce(grantee_role_name, _PUBLIC_GRANTEE).label("grantee"),
            acl_entry.c.privilege_type.label("privilege"),
        )
        .select_from(PgDefaultAcl)
        .outerjoin(
            PgNamespace,
            col(PgNamespace.oid) == col(PgDefaultAcl.defaclnamespace),
        )
        .join(acl_entry, true())
        .outerjoin(PgRoles, col(PgRoles.oid) == acl_entry.c.grantee)
        .where(
            or_(
                func.coalesce(grantee_role_name, "").in_(list(roles)),
                creating_role.in_(list(roles)),
            )
        )
    )
    grouped: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for row in session.execute(statement):
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


def create_missing_roles(session: Session, roles: Iterable[str]) -> list[str]:
    """Create each missing role as NOLOGIN; only for the disposable test database."""
    missing = sorted(set(roles) - read_existing_roles(session, list(roles)))
    quote = _quote(session)
    for role in missing:
        session.execute(text(f"CREATE ROLE {quote(safe_identifier(role))} NOLOGIN"))
    return missing


def apply_declared_privileges(
    session: Session,
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
    *,
    roles_awaiting_creation: Collection[str] = (),
) -> tuple[ReconciliationPlan, list[DefaultPrivilege]]:
    """Grant every declared privilege a role lacks.

    First revokes each whole-table privilege the manifest declares for named
    columns only, which also removes the role's column grants of it, so the
    grants that follow include those columns again. Every other privilege the
    manifest doesn't declare is reported, not revoked. Changes nothing when a
    declared role or table is missing, unless the missing role awaits creation,
    which is skipped.
    """
    roles = list(declared)
    plan = plan_reconciliation(
        declared,
        GrantedPrivileges(
            tables=read_granted_privileges(session, roles),
            columns=read_granted_column_privileges(session, roles),
        ),
        existing_roles=read_existing_roles(session, roles),
        existing_tables=read_public_tables(session),
        roles_awaiting_creation=roles_awaiting_creation,
    )
    if plan.can_apply:
        quote = _quote(session)
        for statement in revoke_statements(plan, quote) + grant_statements(plan, quote):
            session.execute(text(statement))
    return plan, read_default_privileges(session, roles)


def skipped_roles(
    session: Session,
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
    roles_awaiting_creation: Collection[str],
) -> tuple[str, ...]:
    """Return the declared roles awaiting creation that don't exist yet."""
    existing_roles = read_existing_roles(session, list(declared))
    return tuple(
        sorted((set(declared) & set(roles_awaiting_creation)) - existing_roles)
    )


def _privilege_checks(
    session: Session, roles: Collection[str]
) -> tuple[Callable[[str, str, str], bool], Callable[[str, str, str, str], bool]]:
    """Return checks of a role's effective table and column privileges.

    A missing role or table holds nothing.
    """
    existing_roles = read_existing_roles(session, roles)
    existing_tables = read_public_tables(session)

    def has_privilege(role: str, table: str, privilege: str) -> bool:
        if role not in existing_roles or table not in existing_tables:
            return False
        qualified_table = f"{SCHEMA}.{safe_identifier(table)}"
        return bool(
            session.execute(
                select(func.has_table_privilege(role, qualified_table, privilege))
            ).scalar_one()
        )

    def has_column_privilege(
        role: str, table: str, column: str, privilege: str
    ) -> bool:
        if role not in existing_roles or table not in existing_tables:
            return False
        qualified_table = f"{SCHEMA}.{safe_identifier(table)}"
        return bool(
            session.execute(
                select(
                    func.has_column_privilege(
                        role, qualified_table, safe_identifier(column), privilege
                    )
                )
            ).scalar_one()
        )

    return has_privilege, has_column_privilege


def check_declared_privileges(
    session: Session,
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
) -> list[PrivilegeEntry]:
    """Return every declared privilege a role doesn't effectively hold.

    A missing role or table counts as missing every privilege declared for it;
    leave out the roles ``skipped_roles`` returns to skip them.
    """
    has_privilege, has_column_privilege = _privilege_checks(session, list(declared))
    return verification_failures(declared, has_privilege, has_column_privilege)


def check_table_wide_overrides(
    session: Session,
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
) -> list[PrivilegeEntry]:
    """Return each column privilege a role also holds on the whole table."""
    has_privilege, _has_column_privilege = _privilege_checks(session, list(declared))
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
    session: Session,
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
    skipped = skipped_roles(session, declared, roles_awaiting_creation)
    checked = {role: tables for role, tables in declared.items() if role not in skipped}
    failures = check_declared_privileges(session, checked)
    overrides = check_table_wide_overrides(session, checked)
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


def open_reconciliation_sessions(
    settings: V2AlembicSettings,
) -> AbstractContextManager[sessionmaker[Session]]:
    """Open Session factories for the target, on an engine with no pool."""
    from policyengine_api.data.v2.database import unpooled_v2_sessions

    return unpooled_v2_sessions(settings.url)


def run(
    mode: str,
    *,
    create_roles: bool = False,
    environ: Mapping[str, str] | None = None,
    session_factories: Callable[
        [V2AlembicSettings], AbstractContextManager[sessionmaker[Session]]
    ] = open_reconciliation_sessions,
) -> int:
    """Run ``apply`` or ``verify`` against the configured v2 database.

    Everything runs in one transaction, which commits when the mode finishes.
    """
    values = os.environ if environ is None else environ
    settings = load_v2_alembic_settings(values)
    environment = _deployment_environment(values, settings)
    if create_roles and not settings.disposable_test:
        msg = "--create-missing-roles is only allowed for the disposable test database"
        raise V2ConfigurationError(msg)
    declared = declared_privileges(environment)
    awaiting = ROLES_AWAITING_PROVISIONING
    with session_factories(settings) as sessions, sessions.begin() as session:
        qualify_v2_target(session, settings)
        if mode == "verify":
            return _verify(session, declared, awaiting, environment, values)
        if create_roles:
            created = create_missing_roles(session, declared)
            if created:
                print("Created roles: " + ", ".join(created))
        plan, defaults = apply_declared_privileges(
            session, declared, roles_awaiting_creation=awaiting
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
