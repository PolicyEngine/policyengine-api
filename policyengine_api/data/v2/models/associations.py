"""Canonical SQLModel tables linking v2 users to their domain records."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import TimestampedModel
from policyengine_api.data.v2.models.households import Household
from policyengine_api.data.v2.models.policies import Policy
from policyengine_api.data.v2.models.simulations import Simulation
from policyengine_api.data.v2.models.users import User

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.policy_mappings import (
        LegacyUserPolicyMapping,
    )
    from policyengine_api.data.v2.models.reports import Report


class UserHouseholdAssociation(TimestampedModel, table=True):
    __tablename__ = "user_household_associations"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "household_id",
            name="uq_user_household_associations_user_household",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    household_id: UUID = Field(
        foreign_key="households.id",
        ondelete="CASCADE",
        index=True,
    )
    country: str = Field(max_length=16)
    label: str | None = Field(default=None, max_length=255)

    user: User = Relationship(back_populates="household_associations")
    household: Household = Relationship(back_populates="user_associations")


class UserPolicy(TimestampedModel, table=True):
    __tablename__ = "user_policies"
    __table_args__ = (
        sa.UniqueConstraint(
            "id",
            "country_id",
            name="uq_user_policies_id_country",
        ),
        sa.CheckConstraint(
            "country_id IN ('us', 'uk')",
            name="ck_user_policies_country",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id", "country_id"],
            ["policies.id", "policies.country_id"],
            name="fk_user_policies_policy_country",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_user_policies_country_user_created_id",
            "country_id",
            "user_id",
            "created_at",
            "id",
        ),
        sa.Index(
            "ix_user_policies_country_policy",
            "country_id",
            "policy_id",
        ),
    )

    user_id: str = Field(max_length=255, index=True)
    policy_id: UUID = Field(index=True)
    country_id: str = Field(max_length=2)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, sa_type=sa.Text)

    policy: Policy = Relationship(back_populates="user_associations")
    legacy_mapping: Optional["LegacyUserPolicyMapping"] = Relationship(
        back_populates="association",
        cascade_delete=True,
    )


class UserSimulationAssociation(TimestampedModel, table=True):
    __tablename__ = "user_simulation_associations"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "simulation_id",
            name="uq_user_simulation_associations_user_simulation",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="CASCADE",
        index=True,
    )
    country: str = Field(max_length=16)
    label: str | None = Field(default=None, max_length=255)

    user: User = Relationship(back_populates="simulation_associations")
    simulation: Simulation = Relationship(back_populates="user_associations")


class UserReportAssociation(TimestampedModel, table=True):
    __tablename__ = "user_report_associations"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "report_id",
            name="uq_user_report_associations_user_report",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    report_id: UUID = Field(
        foreign_key="reports.id",
        ondelete="CASCADE",
        index=True,
    )
    country: str = Field(max_length=16)
    label: str | None = Field(default=None, max_length=255)
    last_run_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )

    user: User = Relationship(back_populates="report_associations")
    report: "Report" = Relationship(back_populates="user_associations")
