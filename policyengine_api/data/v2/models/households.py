"""Canonical SQLModel tables for v2 households and household jobs."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import TimestampedModel, enum_type

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.associations import UserHouseholdAssociation
    from policyengine_api.data.v2.models.household_mappings import (
        LegacyHouseholdMapping,
    )


class HouseholdJobStatus(StrEnum):
    """Lifecycle state of a household calculation job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Household(TimestampedModel, table=True):
    """Immutable household input, stored once per canonicalization version and hash.

    ``content_hash`` is the SHA-256 of the canonical document, so saving the same
    household again finds the existing row. Households that saved links use
    cannot be deleted; simulations, reports and household jobs name a household
    without a foreign key.
    """

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

    country_id: str = Field(
        max_length=2,
        foreign_key="countries.id",
        ondelete="RESTRICT",
    )
    default_year: int | None = None
    household_data: dict[str, Any] = Field(
        sa_type=sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    )
    canonicalization_version: int
    content_hash: str = Field(max_length=64)

    user_associations: list["UserHouseholdAssociation"] = Relationship(
        back_populates="household",
    )
    legacy_mappings: list["LegacyHouseholdMapping"] = Relationship(
        back_populates="household"
    )


class HouseholdJob(TimestampedModel, table=True):
    """One calculation of one household for one year under one policy.

    ``policy_id`` is null for current law. ``request_data`` holds the
    calculation's options, such as axes. The job records the catalog version
    and PolicyEngine.py version it ran on, its Modal call, and its status and
    result or error. Its household, policy, dynamic and catalog version are logical
    references to the Public API's rows, without foreign keys: the simulation
    service checks them before it writes the job.
    """

    __tablename__ = "household_jobs"
    __table_args__ = (
        sa.CheckConstraint(
            "year BETWEEN 1900 AND 2200",
            name="ck_household_jobs_year",
        ),
        sa.CheckConstraint(
            "status NOT IN ('succeeded', 'failed') OR completed_at IS NOT NULL",
            name="ck_household_jobs_terminal_completion",
        ),
        sa.Index("ix_household_jobs_status_created_at", "status", "created_at"),
    )

    country: str = Field(max_length=16)
    household_id: UUID = Field(index=True)
    year: int
    request_data: dict[str, Any] = Field(sa_type=sa.JSON)
    policy_id: UUID | None = None
    dynamic_id: UUID | None = None
    tax_benefit_model_version_id: UUID
    country_package_version: str = Field(max_length=128)
    policyengine_version: str = Field(max_length=128)
    status: HouseholdJobStatus = Field(
        default=HouseholdJobStatus.PENDING,
        sa_type=enum_type(HouseholdJobStatus, "v2_household_job_status"),
    )
    modal_call_id: str | None = Field(default=None, max_length=255)
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
