"""Canonical SQLModel table for v2 users."""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import IdentifiedModel

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.associations import (
        UserHouseholdAssociation,
        UserReportAssociation,
        UserSimulationAssociation,
    )
    from policyengine_api.data.v2.models.reports import Report


class User(IdentifiedModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "primary_country IN ('us', 'uk')",
            name="ck_users_primary_country",
        ),
    )

    first_name: str = Field(max_length=255)
    last_name: str = Field(max_length=255)
    email: str = Field(max_length=320, index=True)
    primary_country: str = Field(max_length=2)

    reports: list["Report"] = Relationship(back_populates="user")
    household_associations: list["UserHouseholdAssociation"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    simulation_associations: list["UserSimulationAssociation"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    report_associations: list["UserReportAssociation"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
