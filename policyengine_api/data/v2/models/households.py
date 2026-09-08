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
    from policyengine_api.data.v2.models.household_mappings import (
        LegacyHouseholdMapping,
    )
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
        sa.UniqueConstraint(
            "id",
            "country_id",
            name="uq_households_id_country",
        ),
        sa.UniqueConstraint(
            "canonicalization_version",
            "content_hash",
            name="uq_households_canonicalization_content_hash",
        ),
        sa.CheckConstraint(
            "country_id IN ('us', 'uk')",
            name="ck_households_country",
        ),
        sa.CheckConstraint(
            "default_year IS NULL OR default_year BETWEEN 1900 AND 2200",
            name="ck_households_default_year",
        ),
        sa.CheckConstraint(
            "canonicalization_version > 0",
            name="ck_households_canonicalization_version",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_households_content_hash_length",
        ),
        sa.Index(
            "ix_households_country_default_year_created_id",
            "country_id",
            "default_year",
            "created_at",
            "id",
        ),
    )

    country_id: str = Field(max_length=2)
    default_year: int | None = None
    household_data: dict[str, Any] = Field(
        sa_type=sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")
    )
    canonicalization_version: int
    content_hash: str = Field(max_length=64)

    simulations: list["Simulation"] = Relationship(back_populates="household")
    reports: list["Report"] = Relationship(back_populates="household")
    user_associations: list["UserHouseholdAssociation"] = Relationship(
        back_populates="household",
    )
    legacy_mappings: list["LegacyHouseholdMapping"] = Relationship(
        back_populates="household"
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
