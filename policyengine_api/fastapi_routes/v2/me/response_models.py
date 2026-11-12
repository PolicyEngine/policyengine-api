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
        LatestTypeChangeRead,
    )
    from policyengine_api.services.v2.user_invitations.types import (
        InvitationAcceptance,
    )

SignedInUserType = Literal["standard", "author", "admin"]


class StrictAccountAPIModel(BaseModel):
    """Base for account responses; rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class MeItem(StrictAccountAPIModel):
    """The current user: a signed-in account or a browser's unauthenticated user.

    ``user_type`` says which: ``unauthenticated``, or the signed-in user's
    stored type, ``standard``, ``author`` or ``admin``, where each type has
    every permission of the types before it. An unauthenticated user has no
    primary country, and only a signed-in user can set its names or primary
    country.
    """

    id: UUID
    user_type: Literal["unauthenticated", "standard", "author", "admin"]
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


class LatestTypeChangeItem(StrictAccountAPIModel):
    """The user's most recent type change, from ``previous_user_type``."""

    id: UUID
    previous_user_type: SignedInUserType
    user_type: SignedInUserType
    changed_at: datetime

    @classmethod
    def from_read(cls, change: LatestTypeChangeRead) -> LatestTypeChangeItem:
        """Convert the service's read model; the types are validated as literals."""
        return cls.model_validate(
            {
                "id": change.id,
                "previous_user_type": change.previous_user_type.value,
                "user_type": change.user_type.value,
                "changed_at": change.changed_at,
            }
        )


class MeReadResult(StrictAccountAPIModel):
    """The current user, and their most recent type change until it is dismissed.

    ``latest_type_change`` is null when the user's type never changed, when
    its most recent change was dismissed, and for an unauthenticated user.
    """

    item: MeItem
    latest_type_change: LatestTypeChangeItem | None

    @classmethod
    def from_read(cls, account: AccountRead) -> MeReadResult:
        """Build the result from the service's account read."""
        change = account.latest_type_change
        return cls(
            item=MeItem.from_read(account),
            latest_type_change=(
                None if change is None else LatestTypeChangeItem.from_read(change)
            ),
        )


class InvitationAcceptanceItem(StrictAccountAPIModel):
    """The user's type after accepting an invitation, and before.

    ``type_changed`` is false when the user already had the invited type or a
    higher one: an invitation never lowers a type.
    """

    user_type: SignedInUserType
    previous_user_type: SignedInUserType
    type_changed: bool

    @classmethod
    def from_acceptance(
        cls, acceptance: InvitationAcceptance
    ) -> InvitationAcceptanceItem:
        """Convert the service's acceptance; the types are validated as literals."""
        return cls.model_validate(
            {
                "user_type": acceptance.user_type.value,
                "previous_user_type": acceptance.previous_user_type.value,
                "type_changed": acceptance.type_changed,
            }
        )


class InvitationAcceptanceResult(StrictAccountAPIModel):
    """Result holding the accepted invitation's outcome in ``item``."""

    item: InvitationAcceptanceItem


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


class MeReadResponse(AccountSuccessResponse[MeReadResult]):
    """Success response holding the current user and their latest type change."""


class InvitationAcceptanceResponse(AccountSuccessResponse[InvitationAcceptanceResult]):
    """Success response holding an accepted invitation's outcome."""


class MeExportResponse(AccountSuccessResponse[MeExportResult]):
    """Success response holding the current user's export."""


class MeUpgradeResponse(AccountSuccessResponse[MeUpgradeResult]):
    """Success response holding the signed-in account after an upgrade."""
