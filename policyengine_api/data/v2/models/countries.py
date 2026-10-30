"""Canonical SQLModel table recording what each served country supports.

Which countries exist is decided in code: ``policyengine_api.supported_countries``
lists them, and this table must hold exactly one row per listed country. A
row records the calculations its country supports: a household-only country
has ``household_enabled`` set and ``society_wide_enabled`` unset.

``users.primary_country`` and the ``country_id`` of households, policies and
the four user association tables reference ``countries.id``. Other v2 country
columns do not: the mapping tables that pair v1 records with their v2 copies
keep their US-and-UK checks, and the simulation-domain tables, the comparison
run tables and the retired association ``country`` columns store unconstrained
text.
"""

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class Country(SQLModel, table=True):
    """One served country and the calculations it supports.

    A society-wide country must also be household capable. A country that a
    user, household, policy or user association names cannot be deleted.
    """

    __tablename__ = "countries"
    __table_args__ = (
        sa.CheckConstraint(
            "household_enabled OR NOT society_wide_enabled",
            name="ck_countries_society_wide_requires_household",
        ),
    )

    id: str = Field(primary_key=True, max_length=2)
    household_enabled: bool
    society_wide_enabled: bool
