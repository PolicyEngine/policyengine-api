"""Strict HTTP response models for the native v2 policy API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from policyengine_api.fastapi_routes.v2.errors import V2ErrorResponse
from policyengine_api.services.v2.policies.types import PolicyPage, PolicyRead


class StrictPolicyAPIModel(BaseModel):
    """Strict request/response base with dataclass conversion support."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        from_attributes=True,
    )


class PolicyParameterValueItem(StrictPolicyAPIModel):
    id: UUID
    parameter_id: UUID
    parameter_name: str
    value: JsonValue
    start_date: datetime
    end_date: datetime | None


class PolicyItem(StrictPolicyAPIModel):
    id: UUID
    country_id: str
    tax_benefit_model_id: UUID
    created_at: datetime
    updated_at: datetime
    parameter_values: list[PolicyParameterValueItem]

    @classmethod
    def from_read(cls, item: PolicyRead) -> "PolicyItem":
        return cls.model_validate(item)


class PolicyDetailResult(StrictPolicyAPIModel):
    item: PolicyItem


class PolicyPageResult(StrictPolicyAPIModel):
    items: list[PolicyItem]
    offset: int
    limit: int
    has_more: bool

    @classmethod
    def from_page(cls, page: PolicyPage) -> "PolicyPageResult":
        return cls(
            items=[PolicyItem.from_read(item) for item in page.items],
            offset=page.offset,
            limit=page.limit,
            has_more=page.has_more,
        )


ResultT = TypeVar("ResultT")


class PolicySuccessResponse(StrictPolicyAPIModel, Generic[ResultT]):
    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class PolicyDetailResponse(PolicySuccessResponse[PolicyDetailResult]):
    pass


class PolicyPageResponse(PolicySuccessResponse[PolicyPageResult]):
    pass


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
