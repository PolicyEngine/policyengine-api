"""Plan, state and report the table privileges the v2 manifest declares.

The pure half of ``privilege_reconciliation``: it compares the declared
privileges with what a database grants, writes the GRANT statements, finds the
privileges a role lacks or holds too widely, and renders the reports. It runs
no SQL; ``privilege_reconciliation`` reads the database and runs the result.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from policyengine_api.data.v2.privileges import (
    ColumnPrivilege,
    DeclaredPrivilege,
    TablePrivilege,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

SCHEMA = "public"
SAFE_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class PrivilegeReconciliationError(RuntimeError):
    """Raised when privileges can't be reconciled or don't match the manifest."""


class UnsafeIdentifierError(PrivilegeReconciliationError):
    """Raised for a role or table name that isn't a plain lowercase identifier."""


@dataclass(frozen=True, order=True)
class PrivilegeEntry:
    """One privilege one role holds, or should hold, on one table.

    ``column`` names the one column a column privilege is on; it is empty for a
    privilege on the whole table.
    """

    role: str
    table: str
    privilege: str
    column: str = ""


@dataclass(frozen=True)
class GrantedPrivileges:
    """The managed roles' direct grants in one database.

    ``tables`` holds grants on whole tables, by role then table, and
    ``columns`` grants on columns, by role, table, then column.
    """

    tables: Mapping[str, Mapping[str, Collection[str]]]
    columns: Mapping[str, Mapping[str, Mapping[str, Collection[str]]]] = field(
        default_factory=dict
    )


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
    """What ``apply`` grants and reports for one database.

    ``skipped_roles`` are missing roles awaiting creation by an operator; they
    don't block the plan, and nothing is granted to them.
    """

    grants: tuple[PrivilegeEntry, ...]
    undeclared: tuple[PrivilegeEntry, ...]
    missing_roles: tuple[str, ...]
    missing_tables: tuple[str, ...]
    skipped_roles: tuple[str, ...] = ()

    @property
    def can_apply(self) -> bool:
        """Whether every declared role and table exists, so grants may run."""
        return not self.missing_roles and not self.missing_tables


def _declared_entries(
    role: str, table: str, privileges: Collection[DeclaredPrivilege]
) -> list[PrivilegeEntry]:
    """Return one entry per whole-table privilege and per column of a column one."""
    entries = []
    for privilege in privileges:
        if isinstance(privilege, ColumnPrivilege):
            entries += [
                PrivilegeEntry(role, table, privilege.privilege.value, column)
                for column in privilege.columns
            ]
        else:
            entries.append(PrivilegeEntry(role, table, privilege.value))
    return entries


def plan_reconciliation(
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
    granted: GrantedPrivileges,
    *,
    existing_roles: Collection[str],
    existing_tables: Collection[str],
    roles_awaiting_creation: Collection[str] = (),
) -> ReconciliationPlan:
    """Compare declared privileges with what the database grants.

    A missing role in ``roles_awaiting_creation`` is skipped instead of missing.
    """
    absent_roles = set(declared) - set(existing_roles)
    skipped_roles = tuple(sorted(absent_roles & set(roles_awaiting_creation)))
    missing_roles = tuple(sorted(absent_roles - set(skipped_roles)))
    declared_tables = {table for tables in declared.values() for table in tables}
    missing_tables = tuple(sorted(declared_tables - set(existing_tables)))
    declared_entries = {
        entry
        for role, tables in declared.items()
        for table, privileges in tables.items()
        for entry in _declared_entries(role, table, privileges)
    }
    granted_entries = {
        PrivilegeEntry(role, table, privilege)
        for role, tables in granted.tables.items()
        for table, privileges in tables.items()
        for privilege in privileges
    } | {
        PrivilegeEntry(role, table, privilege, column)
        for role, tables in granted.columns.items()
        for table, columns in tables.items()
        for column, privileges in columns.items()
        for privilege in privileges
    }
    grants = sorted(
        entry
        for entry in declared_entries - granted_entries
        if entry.role not in absent_roles and entry.table not in missing_tables
    )
    undeclared = sorted(granted_entries - declared_entries)
    return ReconciliationPlan(
        grants=tuple(grants),
        undeclared=tuple(undeclared),
        missing_roles=missing_roles,
        missing_tables=missing_tables,
        skipped_roles=skipped_roles,
    )


def safe_identifier(identifier: str) -> str:
    """Return ``identifier`` if it is a plain lowercase SQL name, else raise."""
    if SAFE_IDENTIFIER.fullmatch(identifier) is None:
        msg = f"refusing to use {identifier!r} as a role, table or column name"
        raise UnsafeIdentifierError(msg)
    return identifier


def grant_statements(
    plan: ReconciliationPlan, quote_identifier: Callable[[str], str]
) -> list[str]:
    """Return the GRANTs for a plan, in role and table order.

    Each role and table gets one GRANT of its whole-table privileges, then one
    per column privilege, naming its columns in name order.
    """
    table_privileges: dict[tuple[str, str], set[str]] = defaultdict(set)
    columns_by_privilege: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for entry in plan.grants:
        target = (safe_identifier(entry.role), safe_identifier(entry.table))
        privilege = TablePrivilege(entry.privilege).value
        if entry.column:
            columns_by_privilege[(*target, privilege)].add(
                safe_identifier(entry.column)
            )
        else:
            table_privileges[target].add(privilege)
    statements: list[tuple[tuple[str, str, str], str]] = [
        (
            (role, table, ""),
            f"GRANT {', '.join(sorted(privileges))} ON TABLE "
            f"{quote_identifier(SCHEMA)}.{quote_identifier(table)} "
            f"TO {quote_identifier(role)}",
        )
        for (role, table), privileges in table_privileges.items()
    ]
    statements += [
        (
            (role, table, privilege),
            f"GRANT {privilege} "
            f"({', '.join(quote_identifier(column) for column in sorted(columns))}) "
            f"ON TABLE {quote_identifier(SCHEMA)}.{quote_identifier(table)} "
            f"TO {quote_identifier(role)}",
        )
        for (role, table, privilege), columns in columns_by_privilege.items()
    ]
    return [statement for _target, statement in sorted(statements)]


def verification_failures(
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
    has_privilege: Callable[[str, str, str], bool],
    has_column_privilege: Callable[[str, str, str, str], bool] | None = None,
) -> list[PrivilegeEntry]:
    """Return every declared privilege the role doesn't effectively hold.

    A column privilege is checked on each of its columns with
    ``has_column_privilege``, which is required when one is declared.
    """
    failures = []
    for role, tables in declared.items():
        for table, privileges in tables.items():
            for entry in _declared_entries(role, table, privileges):
                if not entry.column:
                    held = has_privilege(role, table, entry.privilege)
                elif has_column_privilege is None:
                    msg = "checking a column privilege needs has_column_privilege"
                    raise ValueError(msg)
                else:
                    held = has_column_privilege(
                        role, table, entry.column, entry.privilege
                    )
                if not held:
                    failures.append(entry)
    return sorted(failures)


def table_wide_overrides(
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
    has_privilege: Callable[[str, str, str], bool],
) -> list[PrivilegeEntry]:
    """Return each column privilege a role also holds on the whole table.

    Holding it on the whole table lets the role use it on every column, past
    the columns the manifest declares.
    """
    return sorted(
        PrivilegeEntry(role, table, privilege.privilege.value)
        for role, tables in declared.items()
        for table, privileges in tables.items()
        for privilege in privileges
        if isinstance(privilege, ColumnPrivilege)
        and has_privilege(role, table, privilege.privilege.value)
    )


def _privilege_rows(entries: Iterable[PrivilegeEntry]) -> list[str]:
    """Return one row per role and table, naming each column privilege's columns."""
    table_privileges: dict[tuple[str, str], set[str]] = defaultdict(set)
    columns_by_privilege: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for entry in entries:
        target = (entry.role, entry.table)
        if entry.column:
            columns_by_privilege[target][entry.privilege].add(entry.column)
        else:
            table_privileges[target].add(entry.privilege)
    rows = []
    for role, table in sorted(set(table_privileges) | set(columns_by_privilege)):
        described = sorted(table_privileges.get((role, table), ())) + [
            f"{privilege} ({', '.join(sorted(columns))})"
            for privilege, columns in sorted(
                columns_by_privilege.get((role, table), {}).items()
            )
        ]
        rows.append(f"| `{role}` | `{table}` | {', '.join(described)} |")
    return rows


def skipped_roles_line(roles: Iterable[str]) -> str:
    """Return the report sentence naming roles skipped until they are created."""
    return (
        "Declared roles not created yet, skipped until an operator creates them: "
        + ", ".join(f"`{role}`" for role in roles)
    )


def render_summary(
    plan: ReconciliationPlan,
    default_privileges: Sequence[DefaultPrivilege],
    *,
    deployment_environment: str,
    applied: bool,
) -> str:
    """Return the Markdown report for the job summary and the log."""
    lines = [f"## v2 table privileges ({deployment_environment})", ""]
    if plan.skipped_roles:
        lines += [skipped_roles_line(plan.skipped_roles), ""]
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


def _failure_row(failure: PrivilegeEntry) -> str:
    if failure.column:
        return (
            f"- `{failure.role}` lacks {failure.privilege} on column "
            f"`{failure.column}` of `{failure.table}`"
        )
    return f"- `{failure.role}` lacks {failure.privilege} on `{failure.table}`"


def verification_report(
    failures: Sequence[PrivilegeEntry], overrides: Sequence[PrivilegeEntry]
) -> str:
    """Return verify's report of missing privileges and whole-table overrides."""
    sections = []
    if failures:
        rows = "\n".join(_failure_row(failure) for failure in failures)
        sections.append(f"Declared privileges missing after reconciling:\n\n{rows}\n")
    if overrides:
        rows = "\n".join(
            f"- `{override.role}` holds {override.privilege} on the whole of "
            f"`{override.table}`, which overrides its declared columns"
            for override in overrides
        )
        sections.append(
            f"Privileges held on whole tables, past their declared columns:\n\n{rows}\n"
        )
    return "\n".join(sections)
