"""Canonical SQLModel tables for v2 policies and dynamics."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import TimestampedModel
from policyengine_api.data.v2.models.metadata import TaxBenefitModel

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.associations import UserPolicy
    from policyengine_api.data.v2.models.households import HouseholdJob
    from policyengine_api.data.v2.models.metadata import ParameterValue
    from policyengine_api.data.v2.models.reports import Report
    from policyengine_api.data.v2.models.simulations import Simulation


class Policy(TimestampedModel, table=True):
    __tablename__ = "policies"

    name: str = Field(max_length=255)
    description: str | None = None
    tax_benefit_model_id: UUID = Field(
        foreign_key="tax_benefit_models.id",
        ondelete="RESTRICT",
        index=True,
    )

    tax_benefit_model: TaxBenefitModel = Relationship(back_populates="policies")
    parameter_values: list["ParameterValue"] = Relationship(
        back_populates="policy",
        cascade_delete=True,
    )
    simulations: list["Simulation"] = Relationship(back_populates="policy")
    household_jobs: list["HouseholdJob"] = Relationship(back_populates="policy")
    reports: list["Report"] = Relationship(back_populates="policy")
    user_associations: list["UserPolicy"] = Relationship(
        back_populates="policy",
        cascade_delete=True,
    )


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
