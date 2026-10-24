"""Strict HTTP response models for the native v2 household API."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from policyengine_api.fastapi_routes.v2.errors import V2ErrorResponse
from policyengine_api.fastapi_routes.v2.households.document_models import (
    HouseholdDocument,
)
from policyengine_api.query_parameters import CountryId, DefaultYear

if TYPE_CHECKING:
    from policyengine_api.services.v2.households.types import HouseholdRead


class StrictHouseholdAPIModel(BaseModel):
    """Base for household responses; rejects unknown fields and NaN or infinity."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        from_attributes=True,
    )


class HouseholdItem(StrictHouseholdAPIModel):
    """A stored household.

    Households are immutable and deduplicated: creating one with identical
    content returns the existing household and its ``id``.
    """

    id: UUID
    country_id: CountryId
    default_year: DefaultYear | None
    household_data: HouseholdDocument
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, item: HouseholdRead) -> HouseholdItem:
        """Build the response item by validating the service read record's fields."""
        return cls.model_validate(item)


class HouseholdDetailResult(StrictHouseholdAPIModel):
    """Result holding one household in ``item``."""

    item: HouseholdItem


ResultT = TypeVar("ResultT")


class HouseholdSuccessResponse(StrictHouseholdAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class HouseholdDetailResponse(HouseholdSuccessResponse[HouseholdDetailResult]):
    """Success response holding one household."""


HOUSEHOLD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": V2ErrorResponse,
        "description": "The household content or country selection is invalid.",
    },
    404: {
        "model": V2ErrorResponse,
        "description": "The selected household does not exist.",
    },
    409: {
        "model": V2ErrorResponse,
        "description": "Immutable household content conflicts with stored state.",
    },
    413: {
        "model": V2ErrorResponse,
        "description": "The household request body exceeds 1 MiB.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The request does not match the household schema.",
    },
    500: {
        "model": V2ErrorResponse,
        "description": "Stored household integrity validation failed.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": "Supabase household persistence is unavailable.",
    },
}
