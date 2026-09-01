"""Read-only qualification for dormant v2 policy data."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import sys
from typing import Protocol

from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.pool import NullPool
from sqlmodel import create_engine

from policyengine_api.data.v2.models import ParameterValue, Policy, UserPolicy
from policyengine_api.data.v2.settings import (
    V2ConfigurationError,
    V2DatabaseSettings,
    load_v2_migration_database_settings,
)


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

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome": "ok",
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


def read_policy_data_counts(executor: ScalarExecutor) -> PolicyDataCounts:
    """Count only policy-owned rows; canonical catalog values are excluded."""

    return PolicyDataCounts(
        policies=int(executor.scalar(select(func.count()).select_from(Policy)) or 0),
        policy_parameter_values=int(
            executor.scalar(
                select(func.count())
                .select_from(ParameterValue)
                .where(ParameterValue.policy_id.is_not(None))
            )
            or 0
        ),
        user_policies=int(
            executor.scalar(select(func.count()).select_from(UserPolicy)) or 0
        ),
    )


def require_no_retained_policy_data(counts: PolicyDataCounts) -> None:
    """Stop the migration when any predecessor policy row requires a decision."""

    if counts.total:
        raise RetainedPolicyDataError(counts)


def build_qualification_engine(settings: V2DatabaseSettings) -> Engine:
    """Build an isolated connection pool for one qualification attempt."""

    return create_engine(settings.connection.url, poolclass=NullPool)


def _qualify_connection(connection: Connection) -> PolicyDataCounts:
    transaction = connection.begin()
    try:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        counts = read_policy_data_counts(connection)
        require_no_retained_policy_data(counts)
        return counts
    finally:
        transaction.rollback()


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
        evidence = qualify_policy_migration_target()
    except Exception as error:  # noqa: BLE001 - command must emit safe evidence
        print(json.dumps(_error_payload(error), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(evidence.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
