"""Read-only qualification for the Stage 12A user-association reshape.

Revision ``fbb7488ebe8a`` reshapes the dormant ``user_simulation_associations``
and ``user_report_associations`` tables (dropping their v2 foreign keys and
legacy columns and adding a required ``country_id``). Before it is applied,
those tables must be empty. This command reports the row counts of all four
v2 user-association tables through an ORM Session in a read-only, rolled-back
transaction and fails when the revision is pending and a dormant table still
holds rows. It never writes, and it never prints the database URL.

Run against the configured target with ``V2_MIGRATION_DATABASE_URL``,
``V2_SUPABASE_PROJECT_REF``, and ``V2_SUPABASE_ENVIRONMENT`` set::

    uv run python -m policyengine_api.data.v2.user_association_migration_qualification
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import func, select

from policyengine_api.data.v2.models import (
    UserHouseholdAssociation,
    UserPolicy,
    UserReportAssociation,
    UserSimulationAssociation,
)
from policyengine_api.data.v2.pending_revisions import v2_revision_is_pending
from policyengine_api.data.v2.settings import (
    V2ConfigurationError,
    V2DatabaseSettings,
    load_v2_migration_database_settings,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping
    from contextlib import AbstractContextManager

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

USER_ASSOCIATION_MIGRATION_REVISION = "fbb7488ebe8a"


class ScalarExecutor(Protocol):
    """Minimal database interface required by the row-count queries."""

    def scalar(self, statement: object) -> object | None:
        """Return the first column from the first result row."""


@dataclass(frozen=True)
class UserAssociationCounts:
    """Row counts of the four v2 user-association tables."""

    user_policies: int
    user_household_associations: int
    user_simulation_associations: int
    user_report_associations: int

    @property
    def dormant_total(self) -> int:
        """Rows in the two reshaped tables, which must be empty before the reshape."""
        return self.user_simulation_associations + self.user_report_associations

    def as_dict(self) -> dict[str, int]:
        """Return the counts keyed by table name, for the evidence and errors."""
        return {
            "user_policies": self.user_policies,
            "user_household_associations": self.user_household_associations,
            "user_simulation_associations": self.user_simulation_associations,
            "user_report_associations": self.user_report_associations,
        }


@dataclass(frozen=True)
class UserAssociationQualification:
    """Non-secret evidence for one configured Supabase target."""

    environment: str
    project_ref: str
    counts: UserAssociationCounts
    migration_pending: bool

    def as_dict(self) -> dict[str, object]:
        """Return the evidence as the JSON object the qualification command prints."""
        return {
            "outcome": "ok",
            "revision": USER_ASSOCIATION_MIGRATION_REVISION,
            "migration_pending": self.migration_pending,
            "dormant_tables_empty": self.counts.dormant_total == 0,
            "environment": self.environment,
            "project_ref": self.project_ref,
            "counts": self.counts.as_dict(),
        }


class RetainedDormantAssociationError(RuntimeError):
    """Raised when a dormant association table holds rows before the reshape."""

    def __init__(self, counts: UserAssociationCounts) -> None:
        """Keep the counts and say in the message how to proceed safely."""
        self.counts = counts
        super().__init__(
            "the configured Supabase target contains user_simulation_associations="
            f"{counts.user_simulation_associations} and user_report_associations="
            f"{counts.user_report_associations} rows; the Stage 12A reshape "
            "requires both to be empty. Nothing was modified; obtain a reviewed "
            "data-preservation plan before retrying"
        )


def read_user_association_counts(
    executor: ScalarExecutor,
    existing_tables: Collection[str] | None = None,
) -> UserAssociationCounts:
    """Count every row in the four user-association tables."""

    def count(model: type, table_name: str) -> int:
        if existing_tables is not None and table_name not in existing_tables:
            return 0
        return int(executor.scalar(select(func.count()).select_from(model)) or 0)

    return UserAssociationCounts(
        user_policies=count(UserPolicy, "user_policies"),
        user_household_associations=count(
            UserHouseholdAssociation, "user_household_associations"
        ),
        user_simulation_associations=count(
            UserSimulationAssociation, "user_simulation_associations"
        ),
        user_report_associations=count(
            UserReportAssociation, "user_report_associations"
        ),
    )


def require_empty_dormant_associations(
    counts: UserAssociationCounts,
    *,
    migration_pending: bool,
) -> None:
    """Raise RetainedDormantAssociationError if a pending reshape would affect rows."""
    if migration_pending and counts.dormant_total:
        raise RetainedDormantAssociationError(counts)


def user_association_migration_is_pending(session: Session) -> bool:
    """Return whether the Stage 12A revision is in the upgrade path."""
    return v2_revision_is_pending(session, USER_ASSOCIATION_MIGRATION_REVISION)


def open_qualification_sessions(
    settings: V2DatabaseSettings,
) -> AbstractContextManager[sessionmaker[Session]]:
    """Open Session factories for one qualification attempt.

    Their engine keeps no pool, and every transaction is READ ONLY: Postgres
    enforces the read-only session characteristic, which is applied before
    the transaction begins and reset on release.
    """
    from policyengine_api.data.v2.database import unpooled_v2_read_only_sessions

    return unpooled_v2_read_only_sessions(settings.connection.url)


def _public_tables(session: Session) -> list[str]:
    from policyengine_api.data.v2.database import v2_schema_inspector

    return v2_schema_inspector(session).get_table_names(schema="public")


def qualify_user_association_migration(
    environ: Mapping[str, str] | None = None,
    *,
    session_factories: Callable[
        [V2DatabaseSettings], AbstractContextManager[sessionmaker[Session]]
    ] = open_qualification_sessions,
    pending_checker: Callable[[Session], bool] = (
        user_association_migration_is_pending
    ),
) -> UserAssociationQualification:
    """Report counts and stop when a pending reshape would affect rows.

    The revision check and the rows are read in one READ ONLY transaction,
    rolled back when the session closes.
    """
    settings = load_v2_migration_database_settings(environ)
    with session_factories(settings) as sessions, sessions() as session:
        migration_pending = pending_checker(session)
        counts = read_user_association_counts(session, _public_tables(session))
        require_empty_dormant_associations(counts, migration_pending=migration_pending)
    return UserAssociationQualification(
        environment=settings.target.environment,
        project_ref=settings.target.project_ref,
        counts=counts,
        migration_pending=migration_pending,
    )


def _error_payload(error: Exception) -> dict[str, object]:
    safe_errors = (V2ConfigurationError, RetainedDormantAssociationError)
    message = (
        str(error)
        if isinstance(error, safe_errors)
        else "v2 user-association migration qualification failed unexpectedly"
    )
    return {
        "outcome": "error",
        "error": {"type": type(error).__name__, "message": message},
    }


def main() -> int:
    """Run qualification and return a shell-compatible status."""
    try:
        evidence = qualify_user_association_migration()
    except Exception as error:  # noqa: BLE001  # command must emit safe evidence
        print(json.dumps(_error_payload(error), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(evidence.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
