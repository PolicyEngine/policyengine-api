"""Read-only qualification for dormant v2 policy data."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import func, select

from policyengine_api.data.v2.models import ParameterValue, Policy, UserPolicy
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

POLICY_MIGRATION_REVISION = "711ec2f0a5a5"


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
        """The number of affected rows; anything but zero stops the migration."""
        return self.policies + self.policy_parameter_values + self.user_policies

    def as_dict(self) -> dict[str, int]:
        """Return the counts keyed by the names used in evidence and errors."""
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


class RetainedPolicyDataError(RuntimeError):
    """Raised when a target contains policy data requiring preservation."""

    def __init__(self, counts: PolicyDataCounts) -> None:
        """Keep the counts and say in the message how to proceed safely."""
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


def open_qualification_sessions(
    settings: V2DatabaseSettings,
) -> AbstractContextManager[sessionmaker[Session]]:
    """Open Session factories for one qualification attempt.

    Their engine keeps no pool, and every transaction is READ ONLY.
    """
    from policyengine_api.data.v2.database import unpooled_v2_read_only_sessions

    return unpooled_v2_read_only_sessions(settings.connection.url)


def _read_and_require_counts(session: Session) -> PolicyDataCounts:
    from policyengine_api.data.v2.database import v2_schema_inspector

    existing_tables = v2_schema_inspector(session).get_table_names(schema="public")
    counts = read_policy_data_counts(session, existing_tables)
    require_no_retained_policy_data(counts)
    return counts


def policy_migration_is_pending(session: Session) -> bool:
    """Return whether the Phase 10 policy revision is in the upgrade path."""
    return v2_revision_is_pending(session, POLICY_MIGRATION_REVISION)


def qualify_policy_migration_target(
    environ: Mapping[str, str] | None = None,
    *,
    session_factories: Callable[
        [V2DatabaseSettings], AbstractContextManager[sessionmaker[Session]]
    ] = open_qualification_sessions,
) -> PolicyMigrationQualification:
    """Qualify the configured Supabase target without changing it.

    The rows are read in one READ ONLY transaction, rolled back when the
    session closes.
    """
    settings = load_v2_migration_database_settings(environ)
    with session_factories(settings) as sessions, sessions() as session:
        counts = _read_and_require_counts(session)
    return PolicyMigrationQualification(
        environment=settings.target.environment,
        project_ref=settings.target.project_ref,
        counts=counts,
    )


def qualify_policy_migration_if_pending(
    environ: Mapping[str, str] | None = None,
    *,
    session_factories: Callable[
        [V2DatabaseSettings], AbstractContextManager[sessionmaker[Session]]
    ] = open_qualification_sessions,
    pending_checker: Callable[[Session], bool] = policy_migration_is_pending,
) -> PolicyMigrationQualification:
    """Qualify predecessor rows only while the Phase 10 revision is pending.

    The revision check and the rows are read in one READ ONLY transaction,
    rolled back when the session closes.
    """
    settings = load_v2_migration_database_settings(environ)
    with session_factories(settings) as sessions, sessions() as session:
        if not pending_checker(session):
            return PolicyMigrationQualification(
                environment=settings.target.environment,
                project_ref=settings.target.project_ref,
                counts=PolicyDataCounts(0, 0, 0),
                required=False,
            )
        counts = _read_and_require_counts(session)
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
    except Exception as error:  # noqa: BLE001  # command must emit safe evidence
        print(json.dumps(_error_payload(error), sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(evidence.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
