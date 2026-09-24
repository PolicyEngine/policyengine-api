"""Temporary, non-serving SQLModels for Stage 12 comparison-run state."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

from policyengine_api.data.v2.models.base import enum_type, utc_now


class Stage12RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    SKIPPED = "skipped"


class Stage12AggregationStatus(StrEnum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Stage12ResultComparisonStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    RUNNING = "running"
    MATCHED = "matched"
    DIFFERENT = "different"
    FAILED = "failed"


class Stage12SimulationRole(StrEnum):
    BASELINE = "baseline"
    REFORM = "reform"
    STANDALONE = "standalone"


class Stage12RunTimestamps(SQLModel):
    """Timestamp fields shared by the two legacy-named comparison tables."""

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_type=sa.DateTime(timezone=True),
        sa_column_kwargs={"server_default": sa.func.now()},
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_type=sa.DateTime(timezone=True),
        sa_column_kwargs={
            "server_default": sa.func.now(),
            "onupdate": sa.func.now(),
        },
    )
    started_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    retention_expires_at: datetime = Field(sa_type=sa.DateTime(timezone=True))


class Stage12ComparisonReport(Stage12RunTimestamps, table=True):
    """One temporary, non-serving parent for a copied calculation."""

    __tablename__ = "stage12_evaluation_reports"
    __table_args__ = (
        sa.UniqueConstraint(
            "environment",
            "calculation_flow",
            "production_identity",
            "worker_version",
            "version_manifest_sha256",
            name="uq_stage12_eval_reports_identity",
        ),
        sa.CheckConstraint(
            "contract_version = 1",
            name="ck_stage12_eval_reports_contract_version",
        ),
        sa.CheckConstraint(
            "retention_expires_at > created_at",
            name="ck_stage12_eval_reports_retention",
        ),
        sa.CheckConstraint(
            "(aggregate_output_uri IS NULL "
            "AND aggregate_output_sha256 IS NULL "
            "AND aggregate_schema_version IS NULL) OR "
            "(aggregate_output_uri IS NOT NULL "
            "AND aggregate_output_sha256 IS NOT NULL "
            "AND aggregate_schema_version IS NOT NULL)",
            name="ck_stage12_eval_reports_output_fields",
        ),
        sa.CheckConstraint(
            "status != 'succeeded' OR "
            "(aggregation_status = 'succeeded' "
            "AND completed_at IS NOT NULL "
            "AND aggregate_output_uri IS NOT NULL)",
            name="ck_stage12_eval_reports_success",
        ),
        sa.CheckConstraint(
            "status NOT IN ('failed', 'skipped') OR error_code IS NOT NULL",
            name="ck_stage12_eval_reports_error_code",
        ),
        sa.Index(
            "ix_stage12_eval_reports_status_retention",
            "status",
            "retention_expires_at",
        ),
        sa.Index(
            "ix_stage12_eval_reports_production_identity",
            "calculation_flow",
            "production_identity",
        ),
    )

    evaluation_id: UUID = Field(default_factory=uuid4, primary_key=True)
    contract_version: int = Field(default=1)
    status: Stage12RunStatus = Field(
        default=Stage12RunStatus.PENDING,
        sa_type=enum_type(
            Stage12RunStatus,
            "v2_stage12_evaluation_status",
        ),
    )
    aggregation_status: Stage12AggregationStatus = Field(
        default=Stage12AggregationStatus.NOT_STARTED,
        sa_type=enum_type(
            Stage12AggregationStatus,
            "v2_stage12_aggregation_status",
        ),
    )
    environment: str = Field(max_length=255)
    calculation_flow: str = Field(max_length=255)
    originating_request_id: str = Field(max_length=255)
    observability_id: str | None = Field(default=None, max_length=36)
    production_identity: str = Field(max_length=255)
    incumbent_execution_id: str | None = Field(default=None, max_length=255)
    worker_version: str = Field(max_length=255)
    modal_application: str = Field(max_length=255)
    report_coordinator_callable: str = Field(max_length=255)
    version_manifest_sha256: str = Field(max_length=64)
    policyengine_version: str = Field(max_length=255)
    country_package_name: str = Field(max_length=255)
    country_package_version: str = Field(max_length=255)
    country: str = Field(max_length=2)
    dataset_identity: str = Field(max_length=255)
    dataset_uri: str = Field(max_length=2048)
    data_package_name: str = Field(max_length=255)
    data_package_version: str = Field(max_length=255)
    data_artifact_revision: str = Field(max_length=255)
    coordinator_invocation_id: str | None = Field(default=None, max_length=255)
    error_code: str | None = Field(default=None, max_length=64)
    error_summary: str | None = Field(default=None, max_length=512)
    aggregate_output_uri: str | None = Field(default=None, max_length=2048)
    aggregate_output_sha256: str | None = Field(default=None, max_length=64)
    aggregate_schema_version: int | None = Field(default=None)
    comparison_status: Stage12ResultComparisonStatus = Field(
        default=Stage12ResultComparisonStatus.NOT_REQUESTED,
        sa_type=enum_type(
            Stage12ResultComparisonStatus,
            "v2_stage12_result_comparison_status",
        ),
        sa_column_kwargs={"server_default": "not_requested"},
    )
    comparison_output_uri: str | None = Field(default=None, max_length=2048)
    comparison_output_sha256: str | None = Field(default=None, max_length=64)
    comparison_schema_version: int | None = Field(default=None)
    comparison_completed_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    comparison_error_code: str | None = Field(default=None, max_length=64)
    comparison_error_summary: str | None = Field(default=None, max_length=512)

    simulations: list["Stage12ComparisonSimulation"] = Relationship(
        back_populates="report",
        cascade_delete=True,
    )


class Stage12ComparisonSimulation(Stage12RunTimestamps, table=True):
    """One temporary child for one independently computed simulation."""

    __tablename__ = "stage12_evaluation_simulations"
    __table_args__ = (
        sa.UniqueConstraint(
            "evaluation_id",
            "role",
            "input_sha256",
            "worker_version",
            "version_manifest_sha256",
            name="uq_stage12_eval_simulations_identity",
        ),
        sa.CheckConstraint(
            "contract_version = 1",
            name="ck_stage12_eval_simulations_contract_version",
        ),
        sa.CheckConstraint(
            "retention_expires_at > created_at",
            name="ck_stage12_eval_simulations_retention",
        ),
        sa.CheckConstraint(
            "(output_uri IS NULL "
            "AND output_sha256 IS NULL "
            "AND output_schema_version IS NULL "
            "AND row_identity_columns IS NULL "
            "AND row_count IS NULL "
            "AND row_identity_sha256 IS NULL) OR "
            "(output_uri IS NOT NULL "
            "AND output_sha256 IS NOT NULL "
            "AND output_schema_version IS NOT NULL "
            "AND row_identity_columns IS NOT NULL "
            "AND row_count IS NOT NULL "
            "AND row_identity_sha256 IS NOT NULL)",
            name="ck_stage12_eval_simulations_output_fields",
        ),
        sa.CheckConstraint(
            "status != 'succeeded' OR "
            "(completed_at IS NOT NULL AND output_uri IS NOT NULL)",
            name="ck_stage12_eval_simulations_success",
        ),
        sa.CheckConstraint(
            "status NOT IN ('failed', 'skipped') OR error_code IS NOT NULL",
            name="ck_stage12_eval_simulations_error_code",
        ),
        sa.Index(
            "ix_stage12_eval_simulations_parent_status",
            "evaluation_id",
            "status",
        ),
        sa.Index(
            "ix_stage12_eval_simulations_status_retention",
            "status",
            "retention_expires_at",
        ),
    )

    simulation_execution_id: UUID = Field(default_factory=uuid4, primary_key=True)
    evaluation_id: UUID = Field(
        foreign_key="stage12_evaluation_reports.evaluation_id",
        ondelete="CASCADE",
    )
    contract_version: int = Field(default=1)
    role: Stage12SimulationRole = Field(
        sa_type=enum_type(
            Stage12SimulationRole,
            "v2_stage12_simulation_role",
        )
    )
    input_sha256: str = Field(max_length=64)
    worker_version: str = Field(max_length=255)
    modal_application: str = Field(max_length=255)
    simulation_callable: str = Field(max_length=255)
    version_manifest_sha256: str = Field(max_length=64)
    modal_invocation_id: str | None = Field(default=None, max_length=255)
    status: Stage12RunStatus = Field(
        default=Stage12RunStatus.PENDING,
        sa_type=enum_type(
            Stage12RunStatus,
            "v2_stage12_evaluation_status",
        ),
    )
    error_code: str | None = Field(default=None, max_length=64)
    error_summary: str | None = Field(default=None, max_length=512)
    output_uri: str | None = Field(default=None, max_length=2048)
    output_sha256: str | None = Field(default=None, max_length=64)
    output_schema_version: int | None = Field(default=None)
    row_identity_columns: list[str] | None = Field(
        default=None,
        sa_type=sa.JSON(none_as_null=True),
    )
    row_count: int | None = Field(default=None)
    row_identity_sha256: str | None = Field(default=None, max_length=64)

    report: Stage12ComparisonReport = Relationship(back_populates="simulations")
