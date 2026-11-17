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
    """Immutable policy content, stored once per canonicalization version and hash.

    Its parameter values are deleted with it. Policies that saved links use
    cannot be deleted.
    """

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

    country_id: str = Field(
        max_length=2,
        foreign_key="countries.id",
        ondelete="RESTRICT",
    )
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
    """Immutable model assumptions, stored once per canonicalization version and hash.

    A dynamic holds parameter values a simulation applies alongside its
    policy: every parameter under ``gov.simulation.``, plus the US's
    top-level ``simulation.`` (``policyengine_api.dynamic_parameters``). It
    is stored and hashed as a policy is, bound to one catalog version, with
    no name or description: a user's saved dynamics name it. Its parameter
    values are deleted with it.
    """

    __tablename__ = "dynamics"
    __table_args__ = (
        sa.UniqueConstraint(
            "id",
            "country_id",
            name="uq_dynamics_id_country",
        ),
        sa.UniqueConstraint(
            "canonicalization_version",
            "content_hash",
            name="uq_dynamics_canonicalization_content_hash",
        ),
        sa.CheckConstraint(
            "canonicalization_version > 0",
            name="ck_dynamics_canonicalization_version",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_dynamics_content_hash_length",
        ),
    )

    country_id: str = Field(
        max_length=2,
        foreign_key="countries.id",
        ondelete="RESTRICT",
    )
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

    tax_benefit_model: TaxBenefitModel = Relationship(back_populates="dynamics")
    tax_benefit_model_version: "TaxBenefitModelVersion" = Relationship(
        back_populates="dynamics"
    )
    parameter_values: list["ParameterValue"] = Relationship(
        back_populates="dynamic",
        cascade_delete=True,
    )
    simulations: list["Simulation"] = Relationship(back_populates="dynamic")
    household_jobs: list["HouseholdJob"] = Relationship(back_populates="dynamic")
