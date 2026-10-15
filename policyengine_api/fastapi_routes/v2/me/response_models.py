"""Strict HTTP response models for the account resource."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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

if TYPE_CHECKING:
    from policyengine_api.services.v2.user_accounts.types import (
        AccountExport,
        AccountRead,
        AccountUpgrade,
    )


class StrictAccountAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class MeItem(StrictAccountAPIModel):
    id: UUID
    user_type: Literal["unauthenticated", "standard"]
    # Null only for an unauthenticated user.
    primary_country: CountryId | None
    first_name: str | None
    last_name: str | None
    email: str | None
    created_at: datetime

    @classmethod
    def from_read(cls, item: AccountRead) -> MeItem:
        return cls.model_validate(item)


class MeDetailResult(StrictAccountAPIModel):
    item: MeItem


class MeExportResult(StrictAccountAPIModel):
    # Null when an unauthenticated user has not saved anything yet.
    user: MeItem | None
    policies: list[UserPolicyItem]
    households: list[UserHouseholdItem]
    simulations: list[UserSimulationItem]
    reports: list[UserReportItem]

    @classmethod
    def from_export(cls, export: AccountExport) -> MeExportResult:
        return cls(
            user=None if export.user is None else MeItem.from_read(export.user),
            policies=[UserPolicyItem.from_read(item) for item in export.policies],
            households=[
                UserHouseholdItem.from_read(item) for item in export.households
            ],
            simulations=[
                UserSimulationItem.from_read(item) for item in export.simulations
            ],
            reports=[UserReportItem.from_read(item) for item in export.reports],
        )


class MeUpgradeResult(StrictAccountAPIModel):
    item: MeItem
    outcome: Literal["converted", "merged", "none"]

    @classmethod
    def from_upgrade(cls, upgrade: AccountUpgrade) -> MeUpgradeResult:
        return cls(
            item=MeItem.from_read(upgrade.account),
            outcome=upgrade.outcome.value,
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


class MeUpgradeResponse(AccountSuccessResponse[MeUpgradeResult]):
    pass
