"""Strict HTTP response models for v2 household calculations."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from policyengine_api.fastapi_routes.v2.errors_support import (
    V2ErrorResponse,
    V2MissingParametersErrorResponse,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.household_calculations.types import (
        HouseholdCalculationRead,
        HouseholdCalculationSubmitted,
    )

CalculationStatus = Literal["pending", "running", "succeeded", "failed"]


class StrictHouseholdCalculationAPIModel(BaseModel):
    """Base for calculation responses; rejects unknown fields and NaN or infinity."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, from_attributes=True)


class HouseholdCalculationSubmittedItem(StrictHouseholdCalculationAPIModel):
    """A calculation the simulation service accepted.

    Poll ``GET /v2/household-calculations/{calculation_id}`` until ``status``
    is ``succeeded`` or ``failed``. ``year`` is the household's default year,
    which is calculated.
    """

    calculation_id: UUID
    status: CalculationStatus
    country_id: str
    household_id: UUID
    policy_id: UUID | None
    year: int

    @classmethod
    def from_submitted(
        cls, calculation: HouseholdCalculationSubmitted
    ) -> HouseholdCalculationSubmittedItem:
        """Build the response item from the service's accepted calculation."""
        return cls.model_validate(calculation)


class HouseholdCalculationOutputItem(StrictHouseholdCalculationAPIModel):
    """A succeeded calculation's household.

    ``household`` is the stored household in the situation shape (people and
    groups keyed by their record IDs) with each calculated value filled in by
    period. ``warnings`` lists inputs the country model ignored. In the US,
    ``spm_config`` is the SPM selection the calculation applied and
    ``spm_provenance`` its receipt; both are null elsewhere.
    """

    household: dict[str, JsonValue]
    warnings: list[str]
    spm_config: dict[str, JsonValue] | None
    spm_provenance: dict[str, JsonValue] | None


class HouseholdCalculationErrorItem(StrictHouseholdCalculationAPIModel):
    """Why a calculation failed.

    ``code`` is the household function's error code: ``invalid_inputs``,
    with ``input_errors`` naming each input the country model does not
    recognize; ``invalid_household``; ``invalid_spm_selection``, with
    ``spm_error``; ``bundle_mismatch``; or ``calculation_failed``. It is null
    when the calculation failed for another reason, such as a household
    function that raised or was cancelled; ``message`` is then the job's
    one-line error, such as ``household_function_error: …`` or
    ``household_function_cancelled: …``, and submitting again may succeed.
    """

    code: str | None
    message: str
    input_errors: list[dict[str, JsonValue]]
    spm_error: dict[str, JsonValue] | None


class HouseholdCalculationItem(StrictHouseholdCalculationAPIModel):
    """A household calculation and its outcome.

    ``status`` moves from ``pending`` through ``running`` to ``succeeded``,
    with ``result``, or ``failed``, with ``error``. ``catalog_version_id``,
    ``country_package_version`` and ``policyengine_version`` are those the
    calculation runs with.
    """

    calculation_id: UUID
    country_id: str
    household_id: UUID
    policy_id: UUID | None
    year: int
    catalog_version_id: UUID
    country_package_version: str
    policyengine_version: str
    status: CalculationStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: HouseholdCalculationOutputItem | None
    error: HouseholdCalculationErrorItem | None

    @classmethod
    def from_read(
        cls, calculation: HouseholdCalculationRead
    ) -> HouseholdCalculationItem:
        """Build the response item from the service's calculation."""
        return cls.model_validate(calculation)


class HouseholdCalculationSubmittedResult(StrictHouseholdCalculationAPIModel):
    """Result holding the accepted calculation in ``item``."""

    item: HouseholdCalculationSubmittedItem


class HouseholdCalculationResult(StrictHouseholdCalculationAPIModel):
    """Result holding one calculation in ``item``."""

    item: HouseholdCalculationItem


ResultT = TypeVar("ResultT")


class HouseholdCalculationSuccessResponse(
    StrictHouseholdCalculationAPIModel, Generic[ResultT]
):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class HouseholdCalculationSubmittedResponse(
    HouseholdCalculationSuccessResponse[HouseholdCalculationSubmittedResult]
):
    """Success response holding the accepted calculation."""


class HouseholdCalculationResponse(
    HouseholdCalculationSuccessResponse[HouseholdCalculationResult]
):
    """Success response holding one calculation."""


HOUSEHOLD_CALCULATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": V2ErrorResponse,
        "description": "The household, policy or calculation does not exist.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The request does not match the schema.",
    },
    500: {
        "model": V2ErrorResponse,
        "description": (
            "The calculation failed unexpectedly, or a succeeded calculation's "
            "stored result cannot be read."
        ),
    },
    503: {
        "model": V2ErrorResponse,
        "description": "The simulation service or v2 storage is unavailable.",
    },
}

SUBMISSION_REFUSAL_RESPONSES: dict[int | str, dict[str, Any]] = {
    502: {
        "model": V2ErrorResponse,
        "description": (
            "The simulation service accepted the calculation, so its job exists, "
            "but its answer cannot be read; it failed (500); it answered a "
            "status the Public API does not expect, such as 200, a redirect, "
            "408, 409 or 501; its answer was lost after the submission may have "
            "reached it; or a proxy in front of it answered 502, 504, or a 503 "
            "without the simulation service's code, in its place. In each case "
            "it may have created the job, and no route finds a job without its "
            "ID. Submit the household calculation "
            "again; if the first request went through, this creates a second "
            "job. The message gives the simulation service's status and code, "
            "or what came in place of its answer."
        ),
    },
    422: {
        "model": V2MissingParametersErrorResponse | V2ErrorResponse,
        "description": (
            "The request does not match the schema; the country does not offer "
            "household calculations; the household has no default year; the "
            "policy sets parameters the running catalog version does not have "
            "(code missing_parameters, which names them); or the simulation "
            "service refuses the caller's data, with its reason in the message."
        ),
    },
    503: {
        "model": V2ErrorResponse,
        "description": (
            "No job of the submission will run: the simulation service cannot "
            "be reached or is not configured; it refuses a household, policy or "
            "catalog version the Public API has already checked (400); its "
            "authentication, routing, body-size or rate limits refuse the "
            "request; it answers its own 503, naming its code, because it cannot "
            "read its manifest or database or Modal refused the call; or it "
            "refuses in a shape the Public API cannot read. Or v2 storage is "
            "unavailable. The message gives the simulation service's reason "
            "only for a 400, otherwise only its status and code."
        ),
    },
}
