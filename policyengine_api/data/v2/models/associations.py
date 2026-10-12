"""Canonical SQLModel tables linking v2 users to their saved records.

Every association names its target through a nullable v2 reference, a
nullable country-scoped v1 (legacy) reference, or both; a database check
requires at least one. ``client_ref`` carries the browser-local identifier of
an imported record so repeated imports are idempotent per user.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import TimestampedModel
from policyengine_api.data.v2.models.households import Household
from policyengine_api.data.v2.models.policies import Policy
from policyengine_api.data.v2.models.users import User

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.policy_mappings import (
        LegacyUserPolicyMapping,
    )


ASSOCIATION_CLIENT_REF_MAX_LENGTH = 64
USER_POLICY_BASELINES = ("current-law", "current-policy")


def _jsonb_type() -> sa.types.TypeEngine[Any]:
    # Typed JSON storage is one of the reviewed direct-SQLAlchemy exceptions.
    return sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


class UserHouseholdAssociation(TimestampedModel, table=True):
    __tablename__ = "user_household_associations"
    __table_args__ = (
        sa.UniqueConstraint(
            "id",
            "country_id",
            name="uq_user_household_associations_id_country",
        ),
        sa.UniqueConstraint(
            "user_id",
            "client_ref",
            name="uq_user_household_associations_user_client_ref",
        ),
        sa.CheckConstraint(
            "country_id IN ('us', 'uk')",
            name="ck_user_household_associations_country",
        ),
        sa.CheckConstraint(
            "household_id IS NOT NULL OR legacy_household_id IS NOT NULL",
            name="ck_user_household_associations_household_ref",
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "country_id"],
            ["households.id", "households.country_id"],
            name="fk_user_household_associations_household_country",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_user_households_country_user_created_id",
            "country_id",
            "user_id",
            "created_at",
            "id",
        ),
        sa.Index(
            "ix_user_households_country_household",
            "country_id",
            "household_id",
        ),
        sa.Index(
            "ix_user_households_country_legacy_household",
            "country_id",
            "legacy_household_id",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    household_id: UUID | None = Field(default=None, index=True)
    legacy_household_id: int | None = Field(default=None, sa_type=sa.BigInteger)
    country_id: str = Field(max_length=2)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, sa_type=sa.Text)
    client_ref: str | None = Field(
        default=None,
        max_length=ASSOCIATION_CLIENT_REF_MAX_LENGTH,
    )

    user: User = Relationship(back_populates="household_associations")
    household: Household | None = Relationship(back_populates="user_associations")


class UserPolicy(TimestampedModel, table=True):
    __tablename__ = "user_policies"
    __table_args__ = (
        sa.UniqueConstraint(
            "id",
            "country_id",
            name="uq_user_policies_id_country",
        ),
        sa.UniqueConstraint(
            "user_id",
            "client_ref",
            name="uq_user_policies_user_client_ref",
        ),
        sa.CheckConstraint(
            "country_id IN ('us', 'uk')",
            name="ck_user_policies_country",
        ),
        sa.CheckConstraint(
            "policy_id IS NOT NULL OR legacy_policy_id IS NOT NULL",
            name="ck_user_policies_policy_ref",
        ),
        sa.CheckConstraint(
            "baseline IS NULL OR baseline IN ('current-law', 'current-policy')",
            name="ck_user_policies_baseline",
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
        sa.Index(
            "ix_user_policies_country_legacy_policy",
            "country_id",
            "legacy_policy_id",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    policy_id: UUID | None = Field(default=None, index=True)
    legacy_policy_id: int | None = Field(default=None, sa_type=sa.BigInteger)
    country_id: str = Field(max_length=2)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, sa_type=sa.Text)
    baseline: str | None = Field(default=None, max_length=16)
    provenance: dict[str, Any] | None = Field(default=None, sa_type=_jsonb_type())
    client_ref: str | None = Field(
        default=None,
        max_length=ASSOCIATION_CLIENT_REF_MAX_LENGTH,
    )

    user: User = Relationship(back_populates="policy_associations")
    policy: Policy | None = Relationship(back_populates="user_associations")
    legacy_mapping: Optional["LegacyUserPolicyMapping"] = Relationship(
        back_populates="association",
        cascade_delete=True,
    )


class UserSimulationAssociation(TimestampedModel, table=True):
    """A user's saved v1 simulation; ``simulation_id`` is a logical reference.

    Simulations are owned by the Simulation Entrypoint, so the v2 reference
    deliberately has no cross-service foreign key.
    """

    __tablename__ = "user_simulation_associations"
    __table_args__ = (
        sa.UniqueConstraint(
            "id",
            "country_id",
            name="uq_user_simulation_associations_id_country",
        ),
        sa.UniqueConstraint(
            "user_id",
            "client_ref",
            name="uq_user_simulation_associations_user_client_ref",
        ),
        sa.CheckConstraint(
            "country_id IN ('us', 'uk')",
            name="ck_user_simulation_associations_country",
        ),
        sa.CheckConstraint(
            "simulation_id IS NOT NULL OR legacy_simulation_id IS NOT NULL",
            name="ck_user_simulation_associations_simulation_ref",
        ),
        sa.Index(
            "ix_user_simulations_country_user_created_id",
            "country_id",
            "user_id",
            "created_at",
            "id",
        ),
        sa.Index(
            "ix_user_simulations_country_legacy_simulation",
            "country_id",
            "legacy_simulation_id",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    simulation_id: UUID | None = Field(default=None, index=True)
    legacy_simulation_id: int | None = Field(default=None, sa_type=sa.BigInteger)
    country_id: str = Field(max_length=2)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, sa_type=sa.Text)
    client_ref: str | None = Field(
        default=None,
        max_length=ASSOCIATION_CLIENT_REF_MAX_LENGTH,
    )

    user: User = Relationship(back_populates="simulation_associations")


class UserReportAssociation(TimestampedModel, table=True):
    """A user's saved v1 report; ``report_id`` is a logical reference.

    ``legacy_report_id`` is the requested v1 report output identifier. The
    optional ``user_policy_id`` links a v3 report to the same owner's saved
    reform and is cleared when that reform is deleted.
    """

    __tablename__ = "user_report_associations"
    __table_args__ = (
        sa.UniqueConstraint(
            "id",
            "country_id",
            name="uq_user_report_associations_id_country",
        ),
        sa.UniqueConstraint(
            "user_id",
            "client_ref",
            name="uq_user_report_associations_user_client_ref",
        ),
        sa.CheckConstraint(
            "country_id IN ('us', 'uk')",
            name="ck_user_report_associations_country",
        ),
        sa.CheckConstraint(
            "report_id IS NOT NULL OR legacy_report_id IS NOT NULL",
            name="ck_user_report_associations_report_ref",
        ),
        sa.Index(
            "ix_user_reports_country_user_created_id",
            "country_id",
            "user_id",
            "created_at",
            "id",
        ),
        sa.Index(
            "ix_user_reports_country_legacy_report",
            "country_id",
            "legacy_report_id",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    report_id: UUID | None = Field(default=None, index=True)
    legacy_report_id: int | None = Field(default=None, sa_type=sa.BigInteger)
    country_id: str = Field(max_length=2)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, sa_type=sa.Text)
    user_policy_id: UUID | None = Field(
        default=None,
        foreign_key="user_policies.id",
        ondelete="SET NULL",
        index=True,
    )
    source_note: str | None = Field(default=None, sa_type=sa.Text)
    provisions: list[Any] | None = Field(default=None, sa_type=_jsonb_type())
    validation: dict[str, Any] | None = Field(default=None, sa_type=_jsonb_type())
    last_run_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    client_ref: str | None = Field(
        default=None,
        max_length=ASSOCIATION_CLIENT_REF_MAX_LENGTH,
    )

    user: User = Relationship(back_populates="report_associations")
