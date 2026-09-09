"""Durable source-identity mappings for immutable v1 households."""

from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import TimestampedModel

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.households import Household


class LegacyHouseholdMapping(TimestampedModel, table=True):
    """Map one country-scoped v1 household ID to deduplicated v2 content."""

    __tablename__ = "legacy_household_mappings"
    __table_args__ = (
        sa.UniqueConstraint(
            "country_id",
            "legacy_household_id",
            name="uq_legacy_household_mappings_country_legacy",
        ),
        sa.CheckConstraint(
            "country_id IN ('us', 'uk')",
            name="ck_legacy_household_mappings_country",
        ),
        sa.CheckConstraint(
            "fingerprint_version > 0",
            name="ck_legacy_household_mappings_fingerprint_version",
        ),
        sa.CheckConstraint(
            "length(fingerprint_sha256) = 64",
            name="ck_legacy_household_mappings_fingerprint_length",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "country_id"],
            ["households.id", "households.country_id"],
            name="fk_legacy_household_mappings_household_country",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_legacy_household_mappings_household",
            "household_id",
        ),
    )

    country_id: str = Field(max_length=2)
    legacy_household_id: int = Field(sa_type=sa.BigInteger)
    household_id: UUID
    source_api_version: str = Field(max_length=255)
    fingerprint_version: int
    fingerprint_sha256: str = Field(max_length=64)

    household: "Household" = Relationship(back_populates="legacy_mappings")
