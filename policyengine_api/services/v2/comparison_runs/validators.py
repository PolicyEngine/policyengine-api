"""Pure validation for temporary Stage 12 comparison-run persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonReportRecord,
    ComparisonRunAggregationStatus,
    ComparisonRunLifecycleStatus,
    ComparisonSimulationRecord,
    ResultComparisonStatus,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


class ComparisonRunNotFoundError(LookupError):
    """Raised when a requested temporary comparison record does not exist."""


class ComparisonRunIdentityError(ValueError):
    """Raised when a retry attempts to reinterpret an existing identity."""


class ComparisonRunStateTransitionError(ValueError):
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
REPORT_RESULT_COMPARISON_FIELDS = (
    "comparison_status",
    "comparison_output_uri",
    "comparison_output_sha256",
    "comparison_schema_version",
    "comparison_completed_at",
    "comparison_error_code",
    "comparison_error_summary",
)

# A completed record is an immutable receipt. A retry may present the same
# receipt with a later observation timestamp, but it may not reinterpret any
# persisted identity, lifecycle, output, error, or completion field.
REPORT_SUCCEEDED_REPLAY_FIELDS = tuple(
    field_name
    for field_name in ComparisonReportRecord.model_fields
    if field_name != "updated_at" and field_name not in REPORT_RESULT_COMPARISON_FIELDS
)
SIMULATION_SUCCEEDED_REPLAY_FIELDS = tuple(
    field_name
    for field_name in ComparisonSimulationRecord.model_fields
    if field_name != "updated_at"
)


def _require_equal_fields(
    existing: object,
    candidate: object,
    fields: Iterable[str],
) -> None:
    for field_name in fields:
        if getattr(existing, field_name) != getattr(candidate, field_name):
            msg = (
                f"comparison-run field {field_name} is immutable for an existing "
                "identity"
            )
            raise ComparisonRunIdentityError(msg)


def require_report_identity(
    existing: ComparisonReportRecord,
    candidate: ComparisonReportRecord,
) -> None:
    """Raise ComparisonRunIdentityError if an update changes an immutable field."""
    _require_equal_fields(existing, candidate, REPORT_IMMUTABLE_FIELDS)


def require_report_conflict_matches(
    existing: ComparisonReportRecord,
    candidate: ComparisonReportRecord,
) -> None:
    """Raise ComparisonRunIdentityError if a duplicate insert names a different release.

    The stored report and the retried record must agree on every release,
    package and dataset field.
    """
    _require_equal_fields(existing, candidate, REPORT_CONFLICT_FIELDS)


def require_simulation_identity(
    existing: ComparisonSimulationRecord,
    candidate: ComparisonSimulationRecord,
) -> None:
    """Raise ComparisonRunIdentityError if an update changes an immutable field."""
    _require_equal_fields(existing, candidate, SIMULATION_IMMUTABLE_FIELDS)


def require_simulation_conflict_matches(
    existing: ComparisonSimulationRecord,
    candidate: ComparisonSimulationRecord,
) -> None:
    """Raise ComparisonRunIdentityError if a duplicate insert names a different worker.

    The stored simulation and the retried record must agree on their parent,
    role, input digest and worker release.
    """
    _require_equal_fields(existing, candidate, SIMULATION_CONFLICT_FIELDS)


def require_simulation_parent_matches(
    parent: ComparisonReportRecord,
    child: ComparisonSimulationRecord,
) -> None:
    """Require a child to retain the parent's release and retention identity."""
    if child.evaluation_id != parent.evaluation_id:
        msg = "comparison child names a different parent evaluation_id"
        raise ComparisonRunIdentityError(msg)
    for field_name in (
        "contract_version",
        "worker_version",
        "modal_application",
        "version_manifest_sha256",
        "created_at",
        "retention_expires_at",
    ):
        if getattr(child, field_name) != getattr(parent, field_name):
            msg = f"comparison child {field_name} does not match its parent"
            raise ComparisonRunIdentityError(msg)


def require_successful_report_replay(
    existing: ComparisonReportRecord,
    candidate: ComparisonReportRecord,
) -> None:
    """Reject attempts to alter an already successful report receipt."""
    _require_equal_fields(existing, candidate, REPORT_SUCCEEDED_REPLAY_FIELDS)


def require_successful_simulation_replay(
    existing: ComparisonSimulationRecord,
    candidate: ComparisonSimulationRecord,
) -> None:
    """Reject attempts to alter an already successful simulation receipt."""
    _require_equal_fields(existing, candidate, SIMULATION_SUCCEEDED_REPLAY_FIELDS)


def require_comparison_update_only(
    existing: ComparisonReportRecord,
    candidate: ComparisonReportRecord,
) -> None:
    """Raise ComparisonRunIdentityError if anything but the comparison fields changes.

    updated_at may also differ; every other report field must match the stored row.
    """
    fields = tuple(
        field_name
        for field_name in ComparisonReportRecord.model_fields
        if field_name != "updated_at"
        and field_name not in REPORT_RESULT_COMPARISON_FIELDS
    )
    _require_equal_fields(existing, candidate, fields)


def require_result_comparison_unchanged(
    existing: ComparisonReportRecord,
    candidate: ComparisonReportRecord,
) -> None:
    """Raise ComparisonRunIdentityError if the result-comparison fields differ."""
    _require_equal_fields(existing, candidate, REPORT_RESULT_COMPARISON_FIELDS)


ALLOWED_TRANSITIONS = {
    ComparisonRunLifecycleStatus.PENDING: frozenset(
        {
            ComparisonRunLifecycleStatus.PENDING,
            ComparisonRunLifecycleStatus.RUNNING,
            ComparisonRunLifecycleStatus.FAILED,
            ComparisonRunLifecycleStatus.SKIPPED,
        }
    ),
    ComparisonRunLifecycleStatus.RUNNING: frozenset(
        {
            ComparisonRunLifecycleStatus.RUNNING,
            ComparisonRunLifecycleStatus.SUCCEEDED,
            ComparisonRunLifecycleStatus.FAILED,
            ComparisonRunLifecycleStatus.INCOMPLETE,
        }
    ),
    ComparisonRunLifecycleStatus.INCOMPLETE: frozenset(
        {
            ComparisonRunLifecycleStatus.INCOMPLETE,
            ComparisonRunLifecycleStatus.RUNNING,
            ComparisonRunLifecycleStatus.FAILED,
        }
    ),
    ComparisonRunLifecycleStatus.SUCCEEDED: frozenset(
        {ComparisonRunLifecycleStatus.SUCCEEDED}
    ),
    ComparisonRunLifecycleStatus.FAILED: frozenset(
        {
            ComparisonRunLifecycleStatus.FAILED,
            ComparisonRunLifecycleStatus.RUNNING,
        }
    ),
    ComparisonRunLifecycleStatus.SKIPPED: frozenset(
        {ComparisonRunLifecycleStatus.SKIPPED}
    ),
}

ALLOWED_AGGREGATION_TRANSITIONS = {
    ComparisonRunAggregationStatus.NOT_STARTED: frozenset(
        {
            ComparisonRunAggregationStatus.NOT_STARTED,
            ComparisonRunAggregationStatus.RUNNING,
            ComparisonRunAggregationStatus.FAILED,
        }
    ),
    ComparisonRunAggregationStatus.RUNNING: frozenset(
        {
            ComparisonRunAggregationStatus.RUNNING,
            ComparisonRunAggregationStatus.SUCCEEDED,
            ComparisonRunAggregationStatus.FAILED,
        }
    ),
    ComparisonRunAggregationStatus.SUCCEEDED: frozenset(
        {ComparisonRunAggregationStatus.SUCCEEDED}
    ),
    ComparisonRunAggregationStatus.FAILED: frozenset(
        {
            ComparisonRunAggregationStatus.FAILED,
            ComparisonRunAggregationStatus.RUNNING,
        }
    ),
}

ALLOWED_RESULT_COMPARISON_TRANSITIONS = {
    ResultComparisonStatus.NOT_REQUESTED: frozenset(
        {ResultComparisonStatus.NOT_REQUESTED}
    ),
    ResultComparisonStatus.PENDING: frozenset(
        {
            ResultComparisonStatus.PENDING,
            ResultComparisonStatus.RUNNING,
            ResultComparisonStatus.MATCHED,
            ResultComparisonStatus.DIFFERENT,
            ResultComparisonStatus.FAILED,
        }
    ),
    ResultComparisonStatus.RUNNING: frozenset(
        {
            ResultComparisonStatus.RUNNING,
            ResultComparisonStatus.MATCHED,
            ResultComparisonStatus.DIFFERENT,
            ResultComparisonStatus.FAILED,
        }
    ),
    ResultComparisonStatus.MATCHED: frozenset({ResultComparisonStatus.MATCHED}),
    ResultComparisonStatus.DIFFERENT: frozenset({ResultComparisonStatus.DIFFERENT}),
    # A failed automatic comparison is final for this temporary execution.
    # Retrying it requires a separately reviewed operator action rather than an
    # implicit state transition during ordinary request processing.
    ResultComparisonStatus.FAILED: frozenset({ResultComparisonStatus.FAILED}),
}


def require_lifecycle_transition(
    current: ComparisonRunLifecycleStatus,
    candidate: ComparisonRunLifecycleStatus,
) -> None:
    """Raise ComparisonRunStateTransitionError if lifecycle cannot move to candidate.

    Every status may repeat; succeeded and skipped are final, and failed or
    incomplete runs may return to running.
    """
    if candidate not in ALLOWED_TRANSITIONS[current]:
        msg = (
            "comparison-run lifecycle cannot move from "
            f"{current.value} to {candidate.value}"
        )
        raise ComparisonRunStateTransitionError(msg)


def require_aggregation_transition(
    current: ComparisonRunAggregationStatus,
    candidate: ComparisonRunAggregationStatus,
) -> None:
    """Raise ComparisonRunStateTransitionError if aggregation cannot move to candidate.

    Every status may repeat; succeeded is final and failed may return to running.
    """
    if candidate not in ALLOWED_AGGREGATION_TRANSITIONS[current]:
        msg = (
            "comparison-run aggregation cannot move "
            f"from {current.value} to {candidate.value}"
        )
        raise ComparisonRunStateTransitionError(msg)


def require_result_comparison_transition(
    current: ResultComparisonStatus,
    candidate: ResultComparisonStatus,
) -> None:
    """Raise ComparisonRunStateTransitionError if comparison cannot move to candidate.

    Not-requested, matched, different and failed are all final.
    """
    if candidate not in ALLOWED_RESULT_COMPARISON_TRANSITIONS[current]:
        msg = f"result comparison cannot move from {current.value} to {candidate.value}"
        raise ComparisonRunStateTransitionError(msg)
