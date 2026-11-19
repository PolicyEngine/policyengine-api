"""Strict HTTP response models for the native v2 dynamic API."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import UUID

from pydantic import Field

from policyengine_api.fastapi_routes.v2.errors_support import V2ErrorResponse
from policyengine_api.fastapi_routes.v2.policies.response_models import (
    PolicyParameterValueItem,
    PolicySuccessResponse,
    StrictPolicyAPIModel,
)

if TYPE_CHECKING:
    from policyengine_api.services.v2.dynamics.types import CheckedDynamicRead


class DynamicItem(StrictPolicyAPIModel):
    """A stored dynamic: the model assumptions a simulation applies with its policy.

    Dynamics are stored as policies are: immutable, bound to one catalog
    version and deduplicated, so creating one with identical content returns
    the existing dynamic and its ``id``. A dynamic has no name; a user's saved
    dynamic names it.
    """

    id: UUID
    country_id: str
    tax_benefit_model_id: UUID
    created_at: datetime
    updated_at: datetime
    parameter_values: list[PolicyParameterValueItem]
    missing_parameters: Annotated[
        list[str] | None,
        Field(
            description=(
                "The parameter paths this dynamic sets that the current "
                "tax-benefit model (the catalog of the running PolicyEngine.py "
                "version) no longer has, sorted; empty when it has them all. "
                "Null when that catalog is not published, so nothing could be "
                "checked. A dynamic with missing parameters cannot be run on "
                "the current model."
            )
        ),
    ]

    @classmethod
    def from_read(cls, item: CheckedDynamicRead) -> DynamicItem:
        """Build the response item by validating the service read record's fields."""
        return cls.model_validate(item)


class DynamicDetailResult(StrictPolicyAPIModel):
    """Result holding one dynamic in ``item``."""

    item: DynamicItem


class DynamicDetailResponse(PolicySuccessResponse[DynamicDetailResult]):
    """Success response holding one dynamic."""


class V2PolicyParametersErrorResponse(V2ErrorResponse):
    """A refused dynamic that sets parameters belonging in a policy.

    ``policy_parameters`` names each parameter the dynamic sets that is not
    one of the model's assumptions, sorted.
    """

    code: Literal["policy_parameters"] = "policy_parameters"
    policy_parameters: list[str]


DYNAMIC_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": V2ErrorResponse,
        "description": "The dynamic content or country selection is invalid.",
    },
    404: {
        "model": V2ErrorResponse,
        "description": "The selected dynamic or catalog does not exist.",
    },
    409: {
        "model": V2ErrorResponse,
        "description": "Immutable dynamic identity conflicts with stored state.",
    },
    413: {
        "model": V2ErrorResponse,
        "description": "The dynamic request body exceeds 1 MiB.",
    },
    422: {
        "model": V2PolicyParametersErrorResponse | V2ErrorResponse,
        "description": (
            "The request does not match the dynamic schema (a dynamic sets at "
            "least one value), or the dynamic sets parameters that belong in a "
            "policy (code policy_parameters, naming them)."
        ),
    },
    500: {
        "model": V2ErrorResponse,
        "description": "Stored dynamic integrity validation failed.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": "Supabase dynamic persistence is unavailable.",
    },
}
