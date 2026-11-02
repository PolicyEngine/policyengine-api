"""Strict HTTP response models for the native v2 policy API."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from policyengine_api.fastapi_routes.v2.errors import V2ErrorResponse

if TYPE_CHECKING:
    from policyengine_api.services.v2.policies.types import (
        CheckedPolicyPage,
        CheckedPolicyRead,
    )


class StrictPolicyAPIModel(BaseModel):
    """Strict request/response base with dataclass conversion support."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        from_attributes=True,
    )


class PolicyParameterValueItem(StrictPolicyAPIModel):
    """One value a policy sets for a parameter from ``start_date``.

    ``parameter_name`` is the parameter's path in the model, and a null
    ``end_date`` means the value has no end.
    """

    id: UUID
    parameter_id: UUID
    parameter_name: str
    value: JsonValue
    start_date: datetime
    end_date: datetime | None


class PolicyItem(StrictPolicyAPIModel):
    """A stored policy: parameter values for one tax-benefit model.

    Policies are immutable and deduplicated: creating one with identical
    content returns the existing policy and its ``id``.
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
                "The parameter paths this policy sets that the current "
                "tax-benefit model (the catalog of the running PolicyEngine.py "
                "version) no longer has, sorted; empty when it has them all. "
                "Null when that catalog is not published, so nothing could be "
                "checked. A policy with missing parameters cannot be run on "
                "the current model."
            )
        ),
    ]

    @classmethod
    def from_read(cls, item: CheckedPolicyRead) -> PolicyItem:
        """Build the response item by validating the service read record's fields."""
        return cls.model_validate(item)


class PolicyDetailResult(StrictPolicyAPIModel):
    """Result holding one policy in ``item``."""

    item: PolicyItem


class PolicyPageResult(StrictPolicyAPIModel):
    """One page of policies, oldest first.

    ``offset`` and ``limit`` echo the request; when ``has_more`` is true, ask
    for the next page with ``offset + limit``.
    """

    items: list[PolicyItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: CheckedPolicyPage) -> PolicyPageResult:
        """Build the response page from a service page, converting each item."""
        return cls(
            items=[PolicyItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class PolicySuccessResponse(StrictPolicyAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class PolicyDetailResponse(PolicySuccessResponse[PolicyDetailResult]):
    """Success response holding one policy."""


class PolicyPageResponse(PolicySuccessResponse[PolicyPageResult]):
    """Success response holding one page of policies."""


POLICY_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": V2ErrorResponse,
        "description": "The policy content or country selection is invalid.",
    },
    404: {
        "model": V2ErrorResponse,
        "description": "The selected policy or catalog does not exist.",
    },
    409: {
        "model": V2ErrorResponse,
        "description": "Immutable policy identity conflicts with stored state.",
    },
    413: {
        "model": V2ErrorResponse,
        "description": "The policy request body exceeds 1 MiB.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The request does not match the policy schema.",
    },
    500: {
        "model": V2ErrorResponse,
        "description": "Stored policy integrity validation failed.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": "Supabase policy persistence is unavailable.",
    },
}
