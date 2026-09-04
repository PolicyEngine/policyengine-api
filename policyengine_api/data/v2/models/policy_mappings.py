"""Durable source-identity mappings for immediate v1 policy mirroring."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

from policyengine_api.data.v2.models.base import TimestampedModel, utc_now

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.associations import UserPolicy
    from policyengine_api.data.v2.models.policies import Policy


class LegacyUserMapping(SQLModel, table=True):
    """Map one exact v1 user identifier to one v2 user UUID."""

    __tablename__ = "legacy_user_mappings"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            name="uq_legacy_user_mappings_user_id",
        ),
    )

    legacy_user_id: str = Field(primary_key=True, max_length=255)
    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="RESTRICT",
        index=True,
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_type=sa.DateTime(timezone=True),
        sa_column_kwargs={"server_default": sa.func.now()},
    )


class LegacyPolicyMapping(TimestampedModel, table=True):
    """Map one country-scoped v1 policy ID to deduplicated v2 content."""

    __tablename__ = "legacy_policy_mappings"
    __table_args__ = (
        sa.UniqueConstraint(
            "country_id",
            "legacy_policy_id",
            name="uq_legacy_policy_mappings_country_legacy",
        ),
        sa.CheckConstraint(
            "country_id IN ('us', 'uk')",
            name="ck_legacy_policy_mappings_country",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id", "country_id"],
            ["policies.id", "policies.country_id"],
            name="fk_legacy_policy_mappings_policy_country",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_legacy_policy_mappings_policy",
            "policy_id",
        ),
    )

    country_id: str = Field(max_length=2)
    legacy_policy_id: int = Field(sa_type=sa.BigInteger)
    policy_id: UUID
    source_policy_hash: str = Field(max_length=255)

    policy: "Policy" = Relationship(back_populates="legacy_mappings")


class LegacyUserPolicyMapping(TimestampedModel, table=True):
    """Map one country-scoped v1 saved policy to one v2 association."""

    __tablename__ = "legacy_user_policy_mappings"
    __table_args__ = (
        sa.UniqueConstraint(
            "country_id",
            "legacy_user_policy_id",
            name="uq_legacy_user_policy_mappings_country_legacy",
        ),
        sa.UniqueConstraint(
            "user_policy_id",
            name="uq_legacy_user_policy_mappings_association",
        ),
        sa.CheckConstraint(
            "country_id IN ('us', 'uk')",
            name="ck_legacy_user_policy_mappings_country",
        ),
        sa.CheckConstraint(
            "fingerprint_version > 0",
            name="ck_legacy_user_policy_mappings_fingerprint_version",
        ),
        sa.CheckConstraint(
            "last_applied_source_revision >= 0",
            name="ck_legacy_user_policy_mappings_source_revision",
        ),
        sa.CheckConstraint(
            "length(fingerprint_sha256) = 64",
            name="ck_legacy_user_policy_mappings_fingerprint_length",
        ),
        sa.ForeignKeyConstraint(
            ["user_policy_id", "country_id"],
            ["user_policies.id", "user_policies.country_id"],
            name="fk_legacy_user_policy_mappings_association_country",
            ondelete="CASCADE",
        ),
        sa.Index(
            "ix_legacy_user_policy_mappings_association",
            "user_policy_id",
        ),
    )

    country_id: str = Field(max_length=2)
    legacy_user_policy_id: int = Field(sa_type=sa.BigInteger)
    user_policy_id: UUID
    last_applied_source_revision: int = Field(
        default=0,
        sa_type=sa.BigInteger,
        sa_column_kwargs={"server_default": "0"},
    )
    fingerprint_version: int
    fingerprint_sha256: str = Field(max_length=64)

    association: "UserPolicy" = Relationship(back_populates="legacy_mapping")
