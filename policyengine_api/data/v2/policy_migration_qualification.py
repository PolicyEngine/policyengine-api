"""Read-only qualification for dormant v2 policy data."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
import json
import sys
from typing import Protocol

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, func, inspect, select
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.pool import NullPool
from sqlmodel import create_engine

from policyengine_api.data.v2.models import ParameterValue, Policy, UserPolicy
from policyengine_api.data.v2.settings import (
    V2ConfigurationError,
    V2DatabaseSettings,
    load_v2_migration_database_settings,
)


POLICY_MIGRATION_REVISION = "711ec2f0a5a5"
V2_ALEMBIC_CONFIG = "alembic-v2.ini"


class ScalarExecutor(Protocol):
    """Minimal database interface required by the row-count queries."""

    def scalar(self, statement: object) -> object | None:
        """Return the first column from the first result row."""


@dataclass(frozen=True)
class PolicyDataCounts:
    """Counts of predecessor policy data that the migration would replace."""

    policies: int
    policy_parameter_values: int
    user_policies: int

    @property
    def total(self) -> int:
        return self.policies + self.policy_parameter_values + self.user_policies

    def as_dict(self) -> dict[str, int]:
        return {
            "policies": self.policies,
            "policy_parameter_values": self.policy_parameter_values,
            "user_policies": self.user_policies,
        }


@dataclass(frozen=True)
class PolicyMigrationQualification:
    """Non-secret evidence that one configured Supabase target is empty."""

    environment: str
    project_ref: str
    counts: PolicyDataCounts
    required: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome": "ok",
            "qualification": "performed" if self.required else "not-required",
            "environment": self.environment,
            "project_ref": self.project_ref,
            "counts": self.counts.as_dict(),
        }


class RetainedPolicyDataError(RuntimeError):
    """Raised when a target contains policy data requiring preservation."""

    def __init__(self, counts: PolicyDataCounts) -> None:
        self.counts = counts
        super().__init__(
            "the configured Supabase target contains retained v2 policy data "
            f"(policies={counts.policies}, "
            f"policy_parameter_values={counts.policy_parameter_values}, "
            f"user_policies={counts.user_policies}); migration stopped without "
            "modifying data. Use an empty target or obtain a reviewed data-"
            "preservation plan before retrying"
        )


def read_policy_data_counts(
    executor: ScalarExecutor,
    existing_tables: Collection[str] | None = None,
) -> PolicyDataCounts:
    """Count only policy-owned rows; canonical catalog values are excluded."""

    def table_exists(name: str) -> bool:
        return existing_tables is None or name in existing_tables

    return PolicyDataCounts(
        policies=(
            int(executor.scalar(select(func.count()).select_from(Policy)) or 0)
            if table_exists("policies")
            else 0
        ),
        policy_parameter_values=int(
            executor.scalar(
                select(func.count())
                .select_from(ParameterValue)
                .where(ParameterValue.policy_id.is_not(None))
            )
            or 0
        )
        if table_exists("parameter_values")
        else 0,
        user_policies=(
            int(executor.scalar(select(func.count()).select_from(UserPolicy)) or 0)
            if table_exists("user_policies")
            else 0
        ),
    )


def require_no_retained_policy_data(counts: PolicyDataCounts) -> None:
    """Stop the migration when any predecessor policy row requires a decision."""

    if counts.total:
        raise RetainedPolicyDataError(counts)


def build_qualification_engine(settings: V2DatabaseSettings) -> Engine:
    """Build an isolated connection pool for one qualification attempt."""

    return create_engine(settings.connection.url, poolclass=NullPool)


def _read_and_require_counts(connection: Connection) -> PolicyDataCounts:
    try:
        existing_tables = inspect(connection).get_table_names(schema="public")
    except NoInspectionAvailable:
        existing_tables = None
    counts = read_policy_data_counts(connection, existing_tables)
    require_no_retained_policy_data(counts)
    return counts


def _qualify_connection(connection: Connection) -> PolicyDataCounts:
    transaction = connection.begin()
    try:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        return _read_and_require_counts(connection)
    finally:
        transaction.rollback()


def policy_migration_is_pending(connection: Connection) -> bool:
    """Return whether the Phase 10 policy revision is in the upgrade path."""

    current_heads = MigrationContext.configure(connection).get_current_heads()
    revisions = ScriptDirectory.from_config(
        Config(V2_ALEMBIC_CONFIG)
    ).iterate_revisions("heads", current_heads)
    return POLICY_MIGRATION_REVISION in {migration.revision for migration in revisions}


def qualify_policy_migration_target(
    environ: Mapping[str, str] | None = None,
    *,
    engine_builder: Callable[[V2DatabaseSettings], Engine] = (
        build_qualification_engine
    ),
) -> PolicyMigrationQualification:
    """Qualify the configured Supabase target without changing it."""

    settings = load_v2_migration_database_settings(environ)
    engine = engine_builder(settings)
    try:
        with engine.connect() as connection:
            counts = _qualify_connection(connection)
    finally:
        engine.dispose()
    return PolicyMigrationQualification(
        environment=settings.target.environment,
        project_ref=settings.target.project_ref,
        counts=counts,
    )


def qualify_policy_migration_if_pending(
    environ: Mapping[str, str] | None = None,
    *,
    engine_builder: Callable[[V2DatabaseSettings], Engine] = (
        build_qualification_engine
    ),
    pending_checker: Callable[[Connection], bool] = policy_migration_is_pending,
) -> PolicyMigrationQualification:
    """Qualify predecessor rows only while the Phase 10 revision is pending."""

    settings = load_v2_migration_database_settings(environ)
    engine = engine_builder(settings)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                if not pending_checker(connection):
                    return PolicyMigrationQualification(
                        environment=settings.target.environment,
                        project_ref=settings.target.project_ref,
                        counts=PolicyDataCounts(0, 0, 0),
                        required=False,
                    )
                counts = _read_and_require_counts(connection)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
    return PolicyMigrationQualification(
        environment=settings.target.environment,
        project_ref=settings.target.project_ref,
        counts=counts,
    )


def _error_payload(error: Exception) -> dict[str, object]:
    safe_errors = (V2ConfigurationError, RetainedPolicyDataError)
    message = (
        str(error)
        if isinstance(error, safe_errors)
        else "v2 policy migration qualification failed unexpectedly"
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
        evidence = qualify_policy_migration_if_pending()
    except Exception as error:  # noqa: BLE001 - command must emit safe evidence
        print(json.dumps(_error_payload(error), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(evidence.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
