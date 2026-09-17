"""Cross-service record contracts for temporary Stage 12 evaluation state."""

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
MAX_EVALUATION_RETENTION = timedelta(days=30)


def _validate_retention(created_at: datetime, retention_expires_at: datetime) -> None:
    if created_at.tzinfo is None or retention_expires_at.tzinfo is None:
        raise ValueError("evaluation retention timestamps must include a timezone")
    retention = retention_expires_at - created_at
    if retention <= timedelta(0):
        raise ValueError("evaluation retention must be greater than zero")
    if retention > MAX_EVALUATION_RETENTION:
        raise ValueError("evaluation retention must not exceed 30 days")


class EvaluationLifecycleStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    SKIPPED = "skipped"


class EvaluationAggregationStatus(StrEnum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EvaluationReportRecord(StrictContractModel):
    """Complete producer/consumer contract for one temporary parent row."""

    contract_version: ContractVersion = 1
    evaluation_id: UUID
    status: EvaluationLifecycleStatus
    aggregation_status: EvaluationAggregationStatus
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
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retention_expires_at: datetime

    @model_validator(mode="after")
    def validate_state(self) -> EvaluationReportRecord:
        _validate_retention(self.created_at, self.retention_expires_at)
        output_fields = (
            self.aggregate_output_uri,
            self.aggregate_output_sha256,
            self.aggregate_schema_version,
        )
        if any(value is not None for value in output_fields) and not all(
            value is not None for value in output_fields
        ):
            raise ValueError("aggregate output fields must be supplied together")
        if self.status is EvaluationLifecycleStatus.SUCCEEDED:
            if self.aggregation_status is not EvaluationAggregationStatus.SUCCEEDED:
                raise ValueError("a successful report requires successful aggregation")
            if not all(value is not None for value in output_fields):
                raise ValueError("a successful report requires an aggregate output")
            if self.completed_at is None:
                raise ValueError("a successful report requires completed_at")
        if (
            self.status
            in {
                EvaluationLifecycleStatus.FAILED,
                EvaluationLifecycleStatus.SKIPPED,
            }
            and self.error_code is None
        ):
            raise ValueError("a failed or skipped report requires an error_code")
        return self


class EvaluationSimulationRecord(StrictContractModel):
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
    status: EvaluationLifecycleStatus
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
    def validate_state(self) -> EvaluationSimulationRecord:
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
            raise ValueError("simulation output fields must be supplied together")
        if self.row_identity_columns is not None:
            if not self.row_identity_columns:
                raise ValueError("row_identity_columns must not be empty")
            if len(self.row_identity_columns) != len(set(self.row_identity_columns)):
                raise ValueError("row_identity_columns must be unique")
        if self.status is EvaluationLifecycleStatus.SUCCEEDED:
            if not all(value is not None for value in output_fields):
                raise ValueError("a successful simulation requires an output")
            if self.completed_at is None:
                raise ValueError("a successful simulation requires completed_at")
        if (
            self.status
            in {
                EvaluationLifecycleStatus.FAILED,
                EvaluationLifecycleStatus.SKIPPED,
            }
            and self.error_code is None
        ):
            raise ValueError("a failed or skipped simulation requires an error_code")
        return self


@dataclass(frozen=True)
class EvaluationReportPersistenceResult:
    record: EvaluationReportRecord
    created: bool


@dataclass(frozen=True)
class EvaluationSimulationPersistenceResult:
    record: EvaluationSimulationRecord
    created: bool
