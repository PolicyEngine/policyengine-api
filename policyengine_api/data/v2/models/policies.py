"""Canonical SQLModel tables for v2 policies and dynamics."""

from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import TimestampedModel
from policyengine_api.data.v2.models.metadata import TaxBenefitModel

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.associations import UserPolicy
    from policyengine_api.data.v2.models.households import HouseholdJob
    from policyengine_api.data.v2.models.metadata import (
        ParameterValue,
        TaxBenefitModelVersion,
    )
    from policyengine_api.data.v2.models.policy_mappings import LegacyPolicyMapping
    from policyengine_api.data.v2.models.reports import Report
    from policyengine_api.data.v2.models.simulations import Simulation


class Policy(TimestampedModel, table=True):
    __tablename__ = "policies"
    __table_args__ = (
        sa.UniqueConstraint(
            "id",
            "country_id",
            name="uq_policies_id_country",
        ),
        sa.UniqueConstraint(
            "canonicalization_version",
            "content_hash",
            name="uq_policies_canonicalization_content_hash",
        ),
        sa.CheckConstraint(
            "country_id IN ('us', 'uk')",
            name="ck_policies_country",
        ),
        sa.CheckConstraint(
            "canonicalization_version > 0",
            name="ck_policies_canonicalization_version",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_policies_content_hash_length",
        ),
        sa.Index(
            "ix_policies_country_model",
            "country_id",
            "tax_benefit_model_id",
        ),
        sa.Index(
            "ix_policies_country_model_version",
            "country_id",
            "tax_benefit_model_version_id",
        ),
    )

    country_id: str = Field(max_length=2)
    tax_benefit_model_id: UUID = Field(
        foreign_key="tax_benefit_models.id",
        ondelete="RESTRICT",
        index=True,
    )
    tax_benefit_model_version_id: UUID = Field(
        foreign_key="tax_benefit_model_versions.id",
        ondelete="RESTRICT",
        index=True,
    )
    canonicalization_version: int
    content_hash: str = Field(max_length=64)

    tax_benefit_model: TaxBenefitModel = Relationship(back_populates="policies")
    tax_benefit_model_version: "TaxBenefitModelVersion" = Relationship(
        back_populates="policies"
    )
    parameter_values: list["ParameterValue"] = Relationship(
        back_populates="policy",
        cascade_delete=True,
    )
    simulations: list["Simulation"] = Relationship(back_populates="policy")
    household_jobs: list["HouseholdJob"] = Relationship(back_populates="policy")
    reports: list["Report"] = Relationship(back_populates="policy")
    user_associations: list["UserPolicy"] = Relationship(
        back_populates="policy",
    )
    legacy_mappings: list["LegacyPolicyMapping"] = Relationship(back_populates="policy")


class Dynamic(TimestampedModel, table=True):
    __tablename__ = "dynamics"

    name: str = Field(max_length=255)
    description: str | None = None

    parameter_values: list["ParameterValue"] = Relationship(
        back_populates="dynamic",
        cascade_delete=True,
    )
    simulations: list["Simulation"] = Relationship(back_populates="dynamic")
    household_jobs: list["HouseholdJob"] = Relationship(back_populates="dynamic")
