"""Pure validation for temporary Stage 12 evaluation persistence."""

from __future__ import annotations

from collections.abc import Iterable

from policyengine_api.services.v2.evaluation_executions.types import (
    EvaluationAggregationStatus,
    EvaluationLifecycleStatus,
    EvaluationReportRecord,
    EvaluationSimulationRecord,
)


class EvaluationRecordNotFoundError(LookupError):
    """Raised when a requested temporary evaluation record does not exist."""


class EvaluationRecordIdentityError(ValueError):
    """Raised when a retry attempts to reinterpret an existing identity."""


class EvaluationStateTransitionError(ValueError):
    """Raised when a lifecycle update moves between incompatible states."""


REPORT_IMMUTABLE_FIELDS = (
    "evaluation_id",
    "contract_version",
    "environment",
    "calculation_flow",
    "originating_request_id",
    "production_identity",
    "incumbent_execution_id",
    "worker_version",
    "modal_application",
    "report_coordinator_callable",
    "version_manifest_sha256",
    "policyengine_version",
    "country_package_name",
    "country_package_version",
    "country",
    "dataset_identity",
    "dataset_uri",
    "data_package_name",
    "data_package_version",
    "data_artifact_revision",
    "created_at",
    "retention_expires_at",
)
REPORT_CONFLICT_FIELDS = (
    "contract_version",
    "environment",
    "calculation_flow",
    "production_identity",
    "worker_version",
    "modal_application",
    "report_coordinator_callable",
    "version_manifest_sha256",
    "policyengine_version",
    "country_package_name",
    "country_package_version",
    "country",
    "dataset_identity",
    "dataset_uri",
    "data_package_name",
    "data_package_version",
    "data_artifact_revision",
)
SIMULATION_IMMUTABLE_FIELDS = (
    "simulation_execution_id",
    "evaluation_id",
    "contract_version",
    "role",
    "input_sha256",
    "worker_version",
    "modal_application",
    "simulation_callable",
    "version_manifest_sha256",
    "created_at",
    "retention_expires_at",
)
SIMULATION_CONFLICT_FIELDS = (
    "evaluation_id",
    "contract_version",
    "role",
    "input_sha256",
    "worker_version",
    "modal_application",
    "simulation_callable",
    "version_manifest_sha256",
)

# A completed record is an immutable receipt. A retry may present the same
# receipt with a later observation timestamp, but it may not reinterpret any
# persisted identity, lifecycle, output, error, or completion field.
REPORT_SUCCEEDED_REPLAY_FIELDS = tuple(
    field_name
    for field_name in EvaluationReportRecord.model_fields
    if field_name != "updated_at"
)
SIMULATION_SUCCEEDED_REPLAY_FIELDS = tuple(
    field_name
    for field_name in EvaluationSimulationRecord.model_fields
    if field_name != "updated_at"
)


def _require_equal_fields(
    existing: object,
    candidate: object,
    fields: Iterable[str],
) -> None:
    for field_name in fields:
        if getattr(existing, field_name) != getattr(candidate, field_name):
            raise EvaluationRecordIdentityError(
                f"evaluation field {field_name} is immutable for an existing identity"
            )


def require_report_identity(
    existing: EvaluationReportRecord,
    candidate: EvaluationReportRecord,
) -> None:
    _require_equal_fields(existing, candidate, REPORT_IMMUTABLE_FIELDS)


def require_report_conflict_matches(
    existing: EvaluationReportRecord,
    candidate: EvaluationReportRecord,
) -> None:
    _require_equal_fields(existing, candidate, REPORT_CONFLICT_FIELDS)


def require_simulation_identity(
    existing: EvaluationSimulationRecord,
    candidate: EvaluationSimulationRecord,
) -> None:
    _require_equal_fields(existing, candidate, SIMULATION_IMMUTABLE_FIELDS)


def require_simulation_conflict_matches(
    existing: EvaluationSimulationRecord,
    candidate: EvaluationSimulationRecord,
) -> None:
    _require_equal_fields(existing, candidate, SIMULATION_CONFLICT_FIELDS)


def require_simulation_parent_matches(
    parent: EvaluationReportRecord,
    child: EvaluationSimulationRecord,
) -> None:
    """Require a child to retain the parent's release and retention identity."""

    if child.evaluation_id != parent.evaluation_id:
        raise EvaluationRecordIdentityError(
            "evaluation child names a different parent evaluation_id"
        )
    for field_name in (
        "contract_version",
        "worker_version",
        "modal_application",
        "version_manifest_sha256",
        "created_at",
        "retention_expires_at",
    ):
        if getattr(child, field_name) != getattr(parent, field_name):
            raise EvaluationRecordIdentityError(
                f"evaluation child {field_name} does not match its parent"
            )


def require_successful_report_replay(
    existing: EvaluationReportRecord,
    candidate: EvaluationReportRecord,
) -> None:
    """Reject attempts to alter an already successful report receipt."""

    _require_equal_fields(existing, candidate, REPORT_SUCCEEDED_REPLAY_FIELDS)


def require_successful_simulation_replay(
    existing: EvaluationSimulationRecord,
    candidate: EvaluationSimulationRecord,
) -> None:
    """Reject attempts to alter an already successful simulation receipt."""

    _require_equal_fields(existing, candidate, SIMULATION_SUCCEEDED_REPLAY_FIELDS)


ALLOWED_TRANSITIONS = {
    EvaluationLifecycleStatus.PENDING: frozenset(
        {
            EvaluationLifecycleStatus.PENDING,
            EvaluationLifecycleStatus.RUNNING,
            EvaluationLifecycleStatus.FAILED,
            EvaluationLifecycleStatus.SKIPPED,
        }
    ),
    EvaluationLifecycleStatus.RUNNING: frozenset(
        {
            EvaluationLifecycleStatus.RUNNING,
            EvaluationLifecycleStatus.SUCCEEDED,
            EvaluationLifecycleStatus.FAILED,
            EvaluationLifecycleStatus.INCOMPLETE,
        }
    ),
    EvaluationLifecycleStatus.INCOMPLETE: frozenset(
        {
            EvaluationLifecycleStatus.INCOMPLETE,
            EvaluationLifecycleStatus.RUNNING,
            EvaluationLifecycleStatus.FAILED,
        }
    ),
    EvaluationLifecycleStatus.SUCCEEDED: frozenset(
        {EvaluationLifecycleStatus.SUCCEEDED}
    ),
    EvaluationLifecycleStatus.FAILED: frozenset(
        {
            EvaluationLifecycleStatus.FAILED,
            EvaluationLifecycleStatus.RUNNING,
        }
    ),
    EvaluationLifecycleStatus.SKIPPED: frozenset({EvaluationLifecycleStatus.SKIPPED}),
}

ALLOWED_AGGREGATION_TRANSITIONS = {
    EvaluationAggregationStatus.NOT_STARTED: frozenset(
        {
            EvaluationAggregationStatus.NOT_STARTED,
            EvaluationAggregationStatus.RUNNING,
            EvaluationAggregationStatus.FAILED,
        }
    ),
    EvaluationAggregationStatus.RUNNING: frozenset(
        {
            EvaluationAggregationStatus.RUNNING,
            EvaluationAggregationStatus.SUCCEEDED,
            EvaluationAggregationStatus.FAILED,
        }
    ),
    EvaluationAggregationStatus.SUCCEEDED: frozenset(
        {EvaluationAggregationStatus.SUCCEEDED}
    ),
    EvaluationAggregationStatus.FAILED: frozenset(
        {
            EvaluationAggregationStatus.FAILED,
            EvaluationAggregationStatus.RUNNING,
        }
    ),
}


def require_lifecycle_transition(
    current: EvaluationLifecycleStatus,
    candidate: EvaluationLifecycleStatus,
) -> None:
    if candidate not in ALLOWED_TRANSITIONS[current]:
        raise EvaluationStateTransitionError(
            f"evaluation lifecycle cannot move from {current.value} to {candidate.value}"
        )


def require_aggregation_transition(
    current: EvaluationAggregationStatus,
    candidate: EvaluationAggregationStatus,
) -> None:
    if candidate not in ALLOWED_AGGREGATION_TRANSITIONS[current]:
        raise EvaluationStateTransitionError(
            "evaluation aggregation cannot move "
            f"from {current.value} to {candidate.value}"
        )
