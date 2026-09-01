"""Strict application commands for user-policy associations."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from policyengine_api.query_parameters import CountryId, ResourceId, UserId


class StrictAssociationCommand(BaseModel):
    """Reject fields outside the reviewed association contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class UserPolicyCreateCommand(StrictAssociationCommand):
    country_id: CountryId
    user_id: UserId
    policy_id: ResourceId
    name: Annotated[str, StringConstraints(max_length=255)] | None = None
    description: str | None = None


class UserPolicyPatchCommand(StrictAssociationCommand):
    name: Annotated[str, StringConstraints(max_length=255)] | None = None
    description: str | None = None

    @model_validator(mode="after")
    def require_supplied_field(self) -> "UserPolicyPatchCommand":
        if not self.model_fields_set.intersection({"name", "description"}):
            raise ValueError("At least one of name or description must be supplied")
        return self
