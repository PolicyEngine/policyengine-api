"""Strict HTTP response models for v2 household calculations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from policyengine_api.fastapi_routes.v2.errors import V2ErrorResponse

if TYPE_CHECKING:
    from policyengine_api.services.v2.household_calculations.types import (
        HouseholdCalculationRead,
    )


class StrictHouseholdCalculationAPIModel(BaseModel):
    """Base for calculation responses; rejects unknown fields and NaN or infinity."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, from_attributes=True)


class HouseholdCalculationOutput(StrictHouseholdCalculationAPIModel):
    """A succeeded calculation's household.

    ``household`` is the stored household in the situation shape (people and
    groups keyed by their record IDs) with each calculated value filled in by
    period. ``warnings`` lists inputs the country model ignored. In the US,
    ``spm_config`` is the SPM selection the calculation applied and
    ``spm_provenance`` its receipt; both are null elsewhere.
    ``policyengine_version`` is the PolicyEngine.py version that calculated it.
    """

    household: dict[str, JsonValue]
    warnings: list[str]
    spm_config: dict[str, JsonValue] | None
    spm_provenance: dict[str, JsonValue] | None
    policyengine_version: str | None


class HouseholdCalculationError(StrictHouseholdCalculationAPIModel):
    """Why a calculation failed; ``detail`` holds the calculation's own error."""

    code: str
    message: str
    detail: dict[str, JsonValue] | None


class HouseholdCalculationItem(StrictHouseholdCalculationAPIModel):
    """A household calculation and its outcome.

    ``status`` moves from ``pending`` through ``dispatching`` and ``running``
    to ``succeeded``, with ``result``, or ``failed``, with ``error``. Poll
    ``GET /v2/household-calculations/{calculation_id}`` until it is one of
    those two. ``catalog_version_id`` is the catalog version calculated.
    """

    calculation_id: UUID
    country_id: str
    household_id: UUID
    policy_id: UUID | None
    year: int
    catalog_version_id: UUID
    status: Literal["pending", "dispatching", "running", "succeeded", "failed"]
    created_at: datetime
    completed_at: datetime | None
    result: HouseholdCalculationOutput | None
    error: HouseholdCalculationError | None

    @classmethod
    def from_read(
        cls, calculation: HouseholdCalculationRead
    ) -> HouseholdCalculationItem:
        """Build the response item from the service's calculation."""
        return cls.model_validate(calculation)


class HouseholdCalculationResponse(StrictHouseholdCalculationAPIModel):
    """Success envelope: ``status`` "ok", a null ``message`` and the calculation."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: HouseholdCalculationItem


HOUSEHOLD_CALCULATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": V2ErrorResponse,
        "description": "The household, policy or calculation does not exist.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": (
            "The request does not match the schema, the country does not offer "
            "household calculations, or no year can be chosen."
        ),
    },
    500: {
        "model": V2ErrorResponse,
        "description": "The household calculation request failed unexpectedly.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": (
            "The simulation service, the country's catalog version or v2 "
            "storage is unavailable, or the simulation service cannot "
            "calculate this household."
        ),
    },
}
