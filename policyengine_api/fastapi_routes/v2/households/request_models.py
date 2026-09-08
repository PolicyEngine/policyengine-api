"""Strict HTTP request models for the native v2 household API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from policyengine_api.fastapi_routes.v2.households.document_models import (
    HouseholdDocument,
    UKHouseholdDocument,
    USHouseholdDocument,
)
from policyengine_api.query_parameters import CountryId, DefaultYear
from policyengine_api.services.v2.households.types import NativeHouseholdCreationInput


MAXIMUM_HOUSEHOLD_REQUEST_BYTES = 1_048_576


class HouseholdCreateRequest(BaseModel):
    """Native immutable household content with no presentation or model fields."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    country_id: CountryId
    default_year: DefaultYear
    household_data: HouseholdDocument

    @model_validator(mode="after")
    def require_country_document(self) -> "HouseholdCreateRequest":
        expected_type = (
            USHouseholdDocument if self.country_id == "us" else UKHouseholdDocument
        )
        if not isinstance(self.household_data, expected_type):
            raise ValueError("household_data collections must match country_id")
        return self

    def to_service_input(self) -> NativeHouseholdCreationInput:
        return NativeHouseholdCreationInput.model_validate(
            self.model_dump(mode="python")
        )
