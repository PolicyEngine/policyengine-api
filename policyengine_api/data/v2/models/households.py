"""Canonical SQLModel tables for v2 households and household jobs."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import (
    IdentifiedModel,
    TimestampedModel,
    enum_type,
)
from policyengine_api.data.v2.models.policies import Dynamic, Policy

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.associations import UserHouseholdAssociation
    from policyengine_api.data.v2.models.reports import Report
    from policyengine_api.data.v2.models.simulations import Simulation


class HouseholdJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Household(TimestampedModel, table=True):
    __tablename__ = "households"
    __table_args__ = (
        sa.CheckConstraint(
            "year BETWEEN 1900 AND 2200",
            name="ck_households_year",
        ),
    )

    country: str = Field(max_length=16, index=True)
    year: int
    label: str | None = Field(default=None, max_length=255)
    household_data: dict[str, Any] = Field(sa_type=sa.JSON)

    simulations: list["Simulation"] = Relationship(back_populates="household")
    reports: list["Report"] = Relationship(back_populates="household")
    user_associations: list["UserHouseholdAssociation"] = Relationship(
        back_populates="household",
        cascade_delete=True,
    )


class HouseholdJob(IdentifiedModel, table=True):
    __tablename__ = "household_jobs"
    __table_args__ = (
        sa.Index("ix_household_jobs_status_created_at", "status", "created_at"),
    )

    country: str = Field(max_length=16)
    request_data: dict[str, Any] = Field(sa_type=sa.JSON)
    policy_id: UUID | None = Field(
        default=None,
        foreign_key="policies.id",
        ondelete="SET NULL",
    )
    dynamic_id: UUID | None = Field(
        default=None,
        foreign_key="dynamics.id",
        ondelete="SET NULL",
    )
    status: HouseholdJobStatus = Field(
        default=HouseholdJobStatus.PENDING,
        sa_type=enum_type(HouseholdJobStatus, "v2_household_job_status"),
    )
    error_message: str | None = None
    result: dict[str, Any] | None = Field(default=None, sa_type=sa.JSON)
    started_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )

    policy: Policy | None = Relationship(back_populates="household_jobs")
    dynamic: Dynamic | None = Relationship(back_populates="household_jobs")
