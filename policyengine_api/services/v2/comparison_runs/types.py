"""Cross-service record contracts for temporary Stage 12 comparison runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from policyengine_api.query_parameters import CountryId
from policyengine_api.services.v2.simulations.types import (
    ContractText,
    Sha256Digest,
    SimulationRole,
    StorageUri,
    StrictContractModel,
)

ContractVersion = Literal[1]
ErrorCode = Annotated[str, Field(min_length=1, max_length=64)]
ErrorSummary = Annotated[str, Field(min_length=1, max_length=512)]
MAX_COMPARISON_RUN_ARTIFACT_RETENTION = timedelta(days=30)


def _validate_retention(created_at: datetime, retention_expires_at: datetime) -> None:
    if created_at.tzinfo is None or retention_expires_at.tzinfo is None:
        msg = "comparison retention timestamps must include a timezone"
        raise ValueError(msg)
    retention = retention_expires_at - created_at
    if retention <= timedelta(0):
        msg = "comparison retention must be greater than zero"
        raise ValueError(msg)
    if retention > MAX_COMPARISON_RUN_ARTIFACT_RETENTION:
        msg = "comparison retention must not exceed 30 days"
        raise ValueError(msg)


class ComparisonRunLifecycleStatus(StrEnum):
    """Lifecycle of a comparison report or simulation.

    Succeeded and skipped are final; failed and incomplete runs may restart.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    SKIPPED = "skipped"


class ComparisonRunAggregationStatus(StrEnum):
    """Progress of a comparison report's aggregation step; succeeded is final."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ResultComparisonStatus(StrEnum):
    """Outcome of comparing a comparison run's aggregate with the production result.

    Not-requested, matched, different and failed are final.
    """

    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    RUNNING = "running"
    MATCHED = "matched"
    DIFFERENT = "different"
    FAILED = "failed"


class ComparisonReportRecord(StrictContractModel):
    """Complete producer/consumer contract for one temporary parent row."""

    contract_version: ContractVersion = 1
    evaluation_id: UUID
    status: ComparisonRunLifecycleStatus
    aggregation_status: ComparisonRunAggregationStatus
    environment: ContractText
    calculation_flow: ContractText
    originating_request_id: ContractText
    production_identity: ContractText
    incumbent_execution_id: ContractText | None = None
    worker_version: ContractText
    modal_application: ContractText
    report_coordinator_callable: ContractText
    version_manifest_sha256: Sha256Digest
    policyengine_version: ContractText
    country_package_name: ContractText
    country_package_version: ContractText
    country: CountryId
    dataset_identity: ContractText
    dataset_uri: Annotated[str, Field(min_length=1, max_length=2048)]
    data_package_name: ContractText
    data_package_version: ContractText
    data_artifact_revision: ContractText
    coordinator_invocation_id: ContractText | None = None
    error_code: ErrorCode | None = None
    error_summary: ErrorSummary | None = None
    aggregate_output_uri: StorageUri | None = None
    aggregate_output_sha256: Sha256Digest | None = None
    aggregate_schema_version: Annotated[int, Field(ge=1)] | None = None
    comparison_status: ResultComparisonStatus = ResultComparisonStatus.NOT_REQUESTED
    comparison_output_uri: StorageUri | None = None
    comparison_output_sha256: Sha256Digest | None = None
    comparison_schema_version: Annotated[int, Field(ge=1)] | None = None
    comparison_completed_at: datetime | None = None
    comparison_error_code: ErrorCode | None = None
    comparison_error_summary: ErrorSummary | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retention_expires_at: datetime

    @model_validator(mode="after")
    def validate_state(self) -> ComparisonReportRecord:
        """Reject a report whose lifecycle, output and comparison fields disagree.

        The aggregate output fields are all set or all unset; a succeeded report
        needs successful aggregation, its output and completed_at; a failed or
        skipped one needs an error_code; and the comparison fields must fit
        comparison_status. Retention must be timezone-aware and 1-30 days long.
        """
        _validate_retention(self.created_at, self.retention_expires_at)
        output_fields = (
            self.aggregate_output_uri,
            self.aggregate_output_sha256,
            self.aggregate_schema_version,
        )
        if any(value is not None for value in output_fields) and not all(
            value is not None for value in output_fields
        ):
            msg = "aggregate output fields must be supplied together"
            raise ValueError(msg)
        if self.status is ComparisonRunLifecycleStatus.SUCCEEDED:
            if self.aggregation_status is not ComparisonRunAggregationStatus.SUCCEEDED:
                msg = "a successful report requires successful aggregation"
                raise ValueError(msg)
            if not all(value is not None for value in output_fields):
                msg = "a successful report requires an aggregate output"
                raise ValueError(msg)
            if self.completed_at is None:
                msg = "a successful report requires completed_at"
                raise ValueError(msg)
        if (
            self.status
            in {
                ComparisonRunLifecycleStatus.FAILED,
                ComparisonRunLifecycleStatus.SKIPPED,
            }
            and self.error_code is None
        ):
            msg = "a failed or skipped report requires an error_code"
            raise ValueError(msg)
        comparison_output_fields = (
            self.comparison_output_uri,
            self.comparison_output_sha256,
            self.comparison_schema_version,
        )
        if self.comparison_status in {
            ResultComparisonStatus.NOT_REQUESTED,
            ResultComparisonStatus.PENDING,
            ResultComparisonStatus.RUNNING,
        }:
            if any(value is not None for value in comparison_output_fields):
                msg = "an incomplete comparison cannot reference an output artifact"
                raise ValueError(msg)
            if self.comparison_completed_at is not None:
                msg = "an incomplete comparison cannot have completed_at"
                raise ValueError(msg)
            if self.comparison_error_code is not None:
                msg = "an incomplete comparison cannot have an error_code"
                raise ValueError(msg)
            if self.comparison_error_summary is not None:
                msg = "an incomplete comparison cannot have an error_summary"
                raise ValueError(msg)
        elif self.comparison_status in {
            ResultComparisonStatus.MATCHED,
            ResultComparisonStatus.DIFFERENT,
        }:
            if not all(value is not None for value in comparison_output_fields):
                msg = "a completed comparison requires an output artifact"
                raise ValueError(msg)
            if self.comparison_completed_at is None:
                msg = "a completed comparison requires completed_at"
                raise ValueError(msg)
            if self.comparison_error_code is not None:
                msg = "a completed comparison cannot have an error_code"
                raise ValueError(msg)
            if self.comparison_error_summary is not None:
                msg = "a completed comparison cannot have an error_summary"
                raise ValueError(msg)
        else:
            if any(value is not None for value in comparison_output_fields):
                msg = "a failed comparison cannot reference an output artifact"
                raise ValueError(msg)
            if self.comparison_completed_at is None:
                msg = "a failed comparison requires completed_at"
                raise ValueError(msg)
            if self.comparison_error_code is None:
                msg = "a failed comparison requires an error_code"
                raise ValueError(msg)
        return self


class ComparisonSimulationRecord(StrictContractModel):
    """Complete producer/consumer contract for one temporary child row."""

    contract_version: ContractVersion = 1
    simulation_execution_id: UUID
    evaluation_id: UUID
    role: SimulationRole
    input_sha256: Sha256Digest
    worker_version: ContractText
    modal_application: ContractText
    simulation_callable: ContractText
    version_manifest_sha256: Sha256Digest
    modal_invocation_id: ContractText | None = None
    status: ComparisonRunLifecycleStatus
    error_code: ErrorCode | None = None
    error_summary: ErrorSummary | None = None
    output_uri: StorageUri | None = None
    output_sha256: Sha256Digest | None = None
    output_schema_version: Annotated[int, Field(ge=1)] | None = None
    row_identity_columns: tuple[ContractText, ...] | None = None
    row_count: Annotated[int, Field(ge=0)] | None = None
    row_identity_sha256: Sha256Digest | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retention_expires_at: datetime

    @model_validator(mode="after")
    def validate_state(self) -> ComparisonSimulationRecord:
        """Reject a simulation whose lifecycle and output fields disagree.

        The output artifact and row-identity fields are all set or all unset,
        row_identity_columns is non-empty and unique, a succeeded simulation
        needs its output and completed_at, and a failed or skipped one needs an
        error_code. Retention must be timezone-aware and 1-30 days long.
        """
        _validate_retention(self.created_at, self.retention_expires_at)
        output_fields = (
            self.output_uri,
            self.output_sha256,
            self.output_schema_version,
            self.row_identity_columns,
            self.row_count,
            self.row_identity_sha256,
        )
        if any(value is not None for value in output_fields) and not all(
            value is not None for value in output_fields
        ):
            msg = "simulation output fields must be supplied together"
            raise ValueError(msg)
        if self.row_identity_columns is not None:
            if not self.row_identity_columns:
                msg = "row_identity_columns must not be empty"
                raise ValueError(msg)
            if len(self.row_identity_columns) != len(set(self.row_identity_columns)):
                msg = "row_identity_columns must be unique"
                raise ValueError(msg)
        if self.status is ComparisonRunLifecycleStatus.SUCCEEDED:
            if not all(value is not None for value in output_fields):
                msg = "a successful simulation requires an output"
                raise ValueError(msg)
            if self.completed_at is None:
                msg = "a successful simulation requires completed_at"
                raise ValueError(msg)
        if (
            self.status
            in {
                ComparisonRunLifecycleStatus.FAILED,
                ComparisonRunLifecycleStatus.SKIPPED,
            }
            and self.error_code is None
        ):
            msg = "a failed or skipped simulation requires an error_code"
            raise ValueError(msg)
        return self


@dataclass(frozen=True)
class ComparisonReportPersistenceResult:
    """A stored report record, and whether this call inserted it or found it."""

    record: ComparisonReportRecord
    created: bool


@dataclass(frozen=True)
class ComparisonSimulationPersistenceResult:
    """A stored simulation record, and whether this call inserted it or found it."""

    record: ComparisonSimulationRecord
    created: bool
