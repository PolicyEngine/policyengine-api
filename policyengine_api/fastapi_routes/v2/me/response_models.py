"""Strict HTTP response models for the signed-in account resource."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from policyengine_api.fastapi_routes.v2.user_households.response_models import (
    UserHouseholdItem,
)
from policyengine_api.fastapi_routes.v2.user_policies.response_models import (
    UserPolicyItem,
)
from policyengine_api.fastapi_routes.v2.user_reports.response_models import (
    UserReportItem,
)
from policyengine_api.fastapi_routes.v2.user_simulations.response_models import (
    UserSimulationItem,
)
from policyengine_api.query_parameters import CountryId
from policyengine_api.services.v2.user_accounts.types import (
    AccountExport,
    AccountImportResult,
    AccountRead,
)


class StrictAccountAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class MeItem(StrictAccountAPIModel):
    id: UUID
    primary_country: CountryId
    first_name: str | None
    last_name: str | None
    email: str | None
    created_at: datetime
    account_created: bool = Field(
        description=(
            "True only in the response to the request that created this "
            "PolicyEngine account on first sign-in; false in every other "
            "response, including concurrent first requests that did not create "
            "it."
        )
    )

    @classmethod
    def from_read(cls, item: AccountRead) -> "MeItem":
        return cls.model_validate(item)


class MeDetailResult(StrictAccountAPIModel):
    item: MeItem


class MeExportResult(StrictAccountAPIModel):
    user: MeItem
    policies: list[UserPolicyItem]
    households: list[UserHouseholdItem]
    simulations: list[UserSimulationItem]
    reports: list[UserReportItem]

    @classmethod
    def from_export(cls, export: AccountExport) -> "MeExportResult":
        return cls(
            user=MeItem.from_read(export.user),
            policies=[UserPolicyItem.from_read(item) for item in export.policies],
            households=[
                UserHouseholdItem.from_read(item) for item in export.households
            ],
            simulations=[
                UserSimulationItem.from_read(item) for item in export.simulations
            ],
            reports=[UserReportItem.from_read(item) for item in export.reports],
        )


class MeImportSkip(StrictAccountAPIModel):
    client_ref: str | None
    reason: Literal["invalid", "unknown_legacy_reference", "client_ref_conflict"]


class MeImportResult(StrictAccountAPIModel):
    id_map: dict[str, UUID]
    skipped: list[MeImportSkip]

    @classmethod
    def from_result(cls, result: AccountImportResult) -> "MeImportResult":
        return cls(
            id_map=dict(result.id_map),
            skipped=[
                MeImportSkip(client_ref=skip.client_ref, reason=skip.reason.value)
                for skip in result.skipped
            ],
        )


ResultT = TypeVar("ResultT")


class AccountSuccessResponse(StrictAccountAPIModel, Generic[ResultT]):
    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class MeDetailResponse(AccountSuccessResponse[MeDetailResult]):
    pass


class MeExportResponse(AccountSuccessResponse[MeExportResult]):
    pass


class MeImportResponse(AccountSuccessResponse[MeImportResult]):
    pass
