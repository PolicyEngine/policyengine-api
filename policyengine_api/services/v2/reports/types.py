"""Versioned, framework-independent contracts for one v2 report execution."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from policyengine_api.services.v2.simulations.types import (
    ArtifactReference,
    BundleProvenance,
    Sha256Digest,
    SimulationExecutionInput,
    SimulationRole,
    StrictContractModel,
)

ContractVersion = Literal[1]


class ReportAggregate(StrEnum):
    BUDGET = "budget"
    POVERTY = "poverty"
    INEQUALITY = "inequality"
    DISTRIBUTIONAL = "distributional"
    WINNERS_AND_LOSERS = "winners_and_losers"
    GEOGRAPHIC = "geographic"
    PROGRAM_STATISTICS = "program_statistics"


class ReportExecutionInput(StrictContractModel):
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
    contract_version: ContractVersion = 1
    evaluation_id: UUID
    artifact: ArtifactReference
    aggregate_schema_version: ContractVersion = 1
    baseline_artifact_sha256: Sha256Digest
    reform_artifact_sha256: Sha256Digest
    bundle: BundleProvenance
