"""Canonical SQLModel table for v2 households."""

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import TimestampedModel

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.associations import UserHouseholdAssociation
    from policyengine_api.data.v2.models.household_mappings import (
        LegacyHouseholdMapping,
    )


class Household(TimestampedModel, table=True):
    """Immutable household input, stored once per canonicalization version and hash.

    ``content_hash`` is the SHA-256 of the canonical document, so saving the same
    household again finds the existing row. Households that saved links use
    cannot be deleted.
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
