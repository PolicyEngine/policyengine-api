"""Read-only qualification for retained v2 household data."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, column, func, inspect, select, table
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.pool import NullPool
from sqlmodel import create_engine

from policyengine_api.data.v2.models import Household, UserHouseholdAssociation
from policyengine_api.data.v2.settings import (
    V2ConfigurationError,
    V2DatabaseSettings,
    load_v2_migration_database_settings,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping

HOUSEHOLD_MIGRATION_REVISION = "724b1b11a33e"
V2_ALEMBIC_CONFIG = "alembic-v2.ini"
# A target before the household revision has these tables, but revision
# 363f34954a14 dropped them and their models, so the counts name them
# directly. The existing-table check skips them on a target without them.
SIMULATIONS = table("simulations", column("household_id"))
REPORTS = table("reports", column("household_id"))
HOUSEHOLD_JOBS = table("household_jobs")


class ScalarExecutor(Protocol):
    """Minimal database interface required by the row-count queries."""

    def scalar(self, statement: object) -> object | None:
        """Return the first column from the first result row."""


@dataclass(frozen=True)
class HouseholdDataCounts:
    """Counts of retained rows affected by the household schema replacement."""

    households: int
    user_household_associations: int
    simulation_household_references: int
    report_household_references: int
    household_jobs: int

    @property
    def total(self) -> int:
        """The number of affected rows; anything but zero stops the migration."""
        return sum(self.as_dict().values())

    def as_dict(self) -> dict[str, int]:
        """Return the counts keyed by the names used in evidence and errors."""
        return {
            "households": self.households,
            "user_household_associations": self.user_household_associations,
            "simulation_household_references": self.simulation_household_references,
            "report_household_references": self.report_household_references,
            "household_jobs": self.household_jobs,
        }


@dataclass(frozen=True)
class HouseholdMigrationQualification:
    """Non-secret evidence for one configured Supabase target."""

    environment: str
    project_ref: str
    counts: HouseholdDataCounts
    required: bool = True

    def as_dict(self) -> dict[str, object]:
        """Return the evidence as the JSON object the qualification command prints.

        ``qualification`` is "not-required" when the revision was already applied.
        """
        return {
            "outcome": "ok",
            "qualification": "performed" if self.required else "not-required",
            "environment": self.environment,
            "project_ref": self.project_ref,
            "counts": self.counts.as_dict(),
        }


class RetainedHouseholdDataError(RuntimeError):
    """Raised when a target contains household data requiring preservation."""

    def __init__(self, counts: HouseholdDataCounts) -> None:
        """Keep the counts and say in the message how to proceed safely."""
        self.counts = counts
        rendered_counts = ", ".join(
            f"{name}={count}" for name, count in counts.as_dict().items()
        )
        super().__init__(
            "the configured Supabase target contains retained v2 household data "
            f"({rendered_counts}); migration stopped without modifying data. Use "
            "an empty target or obtain a reviewed data-preservation plan before "
            "retrying"
        )


def read_household_data_counts(
    executor: ScalarExecutor,
    existing_tables: Collection[str] | None = None,
) -> HouseholdDataCounts:
    """Count household rows and every current household-dependent row."""

    def table_exists(name: str) -> bool:
        return existing_tables is None or name in existing_tables

    def count(statement: object, table_name: str) -> int:
        if not table_exists(table_name):
            return 0
        return int(executor.scalar(statement) or 0)

    return HouseholdDataCounts(
        households=count(select(func.count()).select_from(Household), "households"),
        user_household_associations=count(
            select(func.count()).select_from(UserHouseholdAssociation),
            "user_household_associations",
        ),
        simulation_household_references=count(
            select(func.count())
            .select_from(SIMULATIONS)
            .where(SIMULATIONS.c.household_id.is_not(None)),
            SIMULATIONS.name,
        ),
        report_household_references=count(
            select(func.count())
            .select_from(REPORTS)
            .where(REPORTS.c.household_id.is_not(None)),
            REPORTS.name,
        ),
        household_jobs=count(
            select(func.count()).select_from(HOUSEHOLD_JOBS),
            HOUSEHOLD_JOBS.name,
        ),
    )


def require_no_retained_household_data(counts: HouseholdDataCounts) -> None:
    """Stop the migration when any affected row requires a decision."""
    if counts.total:
        raise RetainedHouseholdDataError(counts)


def build_qualification_engine(settings: V2DatabaseSettings) -> Engine:
    """Build an isolated connection pool for one qualification attempt."""
    return create_engine(settings.connection.url, poolclass=NullPool)


def _read_and_require_counts(connection: Connection) -> HouseholdDataCounts:
    try:
        existing_tables = inspect(connection).get_table_names(schema="public")
    except NoInspectionAvailable:
        existing_tables = None
    counts = read_household_data_counts(connection, existing_tables)
    require_no_retained_household_data(counts)
    return counts


def household_migration_is_pending(connection: Connection) -> bool:
    """Return whether the Stage 11 household revision is in the upgrade path."""
    current_heads = MigrationContext.configure(connection).get_current_heads()
    revisions = ScriptDirectory.from_config(
        Config(V2_ALEMBIC_CONFIG)
    ).iterate_revisions("heads", current_heads)
    return HOUSEHOLD_MIGRATION_REVISION in {
        migration.revision for migration in revisions
    }


def qualify_household_migration_target(
    environ: Mapping[str, str] | None = None,
    *,
    engine_builder: Callable[[V2DatabaseSettings], Engine] = (
        build_qualification_engine
    ),
) -> HouseholdMigrationQualification:
    """Qualify the configured Supabase target without changing it."""
    settings = load_v2_migration_database_settings(environ)
    engine = engine_builder(settings)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                counts = _read_and_require_counts(connection)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
    return HouseholdMigrationQualification(
        environment=settings.target.environment,
        project_ref=settings.target.project_ref,
        counts=counts,
    )


def qualify_household_migration_if_pending(
    environ: Mapping[str, str] | None = None,
    *,
    engine_builder: Callable[[V2DatabaseSettings], Engine] = (
        build_qualification_engine
    ),
    pending_checker: Callable[[Connection], bool] = household_migration_is_pending,
) -> HouseholdMigrationQualification:
    """Qualify affected rows only while the Stage 11 revision is pending."""
    settings = load_v2_migration_database_settings(environ)
    engine = engine_builder(settings)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                if not pending_checker(connection):
                    return HouseholdMigrationQualification(
                        environment=settings.target.environment,
                        project_ref=settings.target.project_ref,
                        counts=HouseholdDataCounts(0, 0, 0, 0, 0),
                        required=False,
                    )
                counts = _read_and_require_counts(connection)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
    return HouseholdMigrationQualification(
        environment=settings.target.environment,
        project_ref=settings.target.project_ref,
        counts=counts,
    )


def _error_payload(error: Exception) -> dict[str, object]:
    safe_errors = (V2ConfigurationError, RetainedHouseholdDataError)
    message = (
        str(error)
        if isinstance(error, safe_errors)
        else "v2 household migration qualification failed unexpectedly"
    )
    return {
        "outcome": "error",
        "error": {
            "type": type(error).__name__,
            "message": message,
        },
    }


def main() -> int:
    """Run qualification and return a shell-compatible status."""
    try:
        evidence = qualify_household_migration_if_pending()
    except Exception as error:  # noqa: BLE001  # command must emit safe evidence
        print(json.dumps(_error_payload(error), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(evidence.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
