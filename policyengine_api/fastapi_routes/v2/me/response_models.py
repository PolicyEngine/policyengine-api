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
    """Base for account responses; rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class MeItem(StrictAccountAPIModel):
    """The current user: a signed-in account or a browser's unauthenticated user.

    ``user_type`` says which. An unauthenticated user has no primary country, and
    only a signed-in user can set its names or primary country.
    """

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
        """Build the response item by validating the service read record's fields."""
        return cls.model_validate(item)


class MeDetailResult(StrictAccountAPIModel):
    """Result holding the current user in ``item``."""

    item: MeItem


class MeExportResult(StrictAccountAPIModel):
    """The current user and every policy, household, simulation and report it saved.

    The export covers every country, not only the requested one.
    """

    # Null when an unauthenticated user has not saved anything yet.
    user: MeItem | None
    policies: list[UserPolicyItem]
    households: list[UserHouseholdItem]
    simulations: list[UserSimulationItem]
    reports: list[UserReportItem]

    @classmethod
    def from_export(cls, export: AccountExport) -> MeExportResult:
        """Build the export result from the service export, converting each record."""
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
    """The signed-in account after a browser's unauthenticated user moved into it.

    ``outcome`` is ``converted`` when the unauthenticated user became the account
    in place, ``merged`` when its records moved to an existing account, and
    ``none`` when there was no unauthenticated user to move.
    """

    item: MeItem
    outcome: Literal["converted", "merged", "none"]

    @classmethod
    def from_upgrade(cls, upgrade: AccountUpgrade) -> MeUpgradeResult:
        """Build the upgrade result from the service's account and outcome."""
        return cls(
            item=MeItem.from_read(upgrade.account),
            outcome=upgrade.outcome.value,
        )


ResultT = TypeVar("ResultT")


class AccountSuccessResponse(StrictAccountAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class MeDetailResponse(AccountSuccessResponse[MeDetailResult]):
    """Success response holding the current user."""


class MeExportResponse(AccountSuccessResponse[MeExportResult]):
    """Success response holding the current user's export."""


class MeUpgradeResponse(AccountSuccessResponse[MeUpgradeResult]):
    """Success response holding the signed-in account after an upgrade."""
