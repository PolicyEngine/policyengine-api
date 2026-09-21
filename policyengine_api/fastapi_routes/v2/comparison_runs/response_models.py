"""Strict responses for the internal Stage 12 persistence boundary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonReportRecord,
    ComparisonSimulationRecord,
)


class StrictStage12PersistenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ComparisonReportResponse(StrictStage12PersistenceResponse):
    record: ComparisonReportRecord


class ComparisonReportPersistenceResponse(ComparisonReportResponse):
    created: bool


class ComparisonSimulationResponse(StrictStage12PersistenceResponse):
    record: ComparisonSimulationRecord


class ComparisonSimulationPersistenceResponse(ComparisonSimulationResponse):
    created: bool


class ComparisonSimulationListResponse(StrictStage12PersistenceResponse):
    items: tuple[ComparisonSimulationRecord, ...]
