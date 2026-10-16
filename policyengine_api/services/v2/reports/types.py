"""Versioned, framework-independent contracts for one v2 report execution."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, JsonValue, field_validator, model_validator

from policyengine_api.services.v2.simulations.types import (
    ArtifactReference,
    BundleProvenance,
    Sha256Digest,
    SimulationExecutionInput,
    SimulationRole,
    StrictContractModel,
)
from policyengine_api.spm import SPMComparisonProvenance

ContractVersion = Literal[1]


class ReportAggregate(StrEnum):
    """An aggregate result section a report can request."""

    BUDGET = "budget"
    POVERTY = "poverty"
    INEQUALITY = "inequality"
    DISTRIBUTIONAL = "distributional"
    WINNERS_AND_LOSERS = "winners_and_losers"
    GEOGRAPHIC = "geographic"
    PROGRAM_STATISTICS = "program_statistics"


class ReportExecutionInput(StrictContractModel):
    """The complete input for one report run.

    It pairs a baseline and a reform simulation that differ only in policy, and
    lists the aggregates to compute from them.
    """

    contract_version: ContractVersion = 1
    evaluation_id: UUID
    baseline: SimulationExecutionInput
    reform: SimulationExecutionInput
    requested_aggregates: Annotated[
        tuple[ReportAggregate, ...],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def require_aligned_simulations(self) -> ReportExecutionInput:
        """Reject a report whose two simulations cannot be compared.

        Baseline and reform must carry their own roles and this report's
        evaluation_id, have distinct execution ids, and share population, year,
        geography, options, requested output and bundle. Requested aggregates
        must be unique.
        """
        if self.baseline.role is not SimulationRole.BASELINE:
            raise ValueError("baseline input must use the baseline role")
        if self.reform.role is not SimulationRole.REFORM:
            raise ValueError("reform input must use the reform role")
        if self.baseline.evaluation_id != self.evaluation_id:
            raise ValueError("baseline evaluation_id must match the report")
        if self.reform.evaluation_id != self.evaluation_id:
            raise ValueError("reform evaluation_id must match the report")
        if self.baseline.simulation_execution_id == self.reform.simulation_execution_id:
            raise ValueError("baseline and reform simulation identifiers must differ")
        comparable_fields = (
            "population",
            "year",
            "geography",
            "options",
            "requested_output",
            "bundle",
        )
        for field_name in comparable_fields:
            if getattr(self.baseline, field_name) != getattr(self.reform, field_name):
                raise ValueError(
                    f"baseline and reform {field_name} must match before execution"
                )
        if len(self.requested_aggregates) != len(set(self.requested_aggregates)):
            raise ValueError("requested aggregates must be unique")
        return self


class AggregateReportArtifactDescriptor(StrictContractModel):
    """The receipt for one stored aggregate report.

    It names the artifact and the bundle, and records the digests of the
    baseline and reform simulation artifacts it was computed from.
    """

    contract_version: ContractVersion = 1
    evaluation_id: UUID
    artifact: ArtifactReference
    aggregate_schema_version: ContractVersion = 1
    baseline_artifact_sha256: Sha256Digest
    reform_artifact_sha256: Sha256Digest
    bundle: BundleProvenance


class AggregateReportArtifactPayload(StrictContractModel):
    """Complete JSON payload stored in one aggregate report artifact."""

    contract_version: ContractVersion = 1
    aggregate_schema_version: ContractVersion = 1
    evaluation_id: UUID
    requested_aggregates: Annotated[
        tuple[ReportAggregate, ...],
        Field(min_length=1),
    ]
    bundle: BundleProvenance
    result: dict[str, JsonValue]

    @field_validator("requested_aggregates")
    @classmethod
    def require_unique_aggregates(
        cls,
        value: tuple[ReportAggregate, ...],
    ) -> tuple[ReportAggregate, ...]:
        """Reject a payload that lists any aggregate twice."""
        if len(value) != len(set(value)):
            raise ValueError("requested aggregates must be unique")
        return value

    @model_validator(mode="after")
    def validate_spm_provenance(self) -> AggregateReportArtifactPayload:
        """Reject duplicate or noncanonical SPM data in aggregate artifacts."""
        if "spm_config" in self.result:
            raise ValueError("aggregate result must not include legacy spm_config")
        if "spm_provenance" in self.result:
            SPMComparisonProvenance.model_validate(self.result["spm_provenance"])
        return self
