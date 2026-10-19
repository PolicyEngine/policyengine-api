"""Canonical SQLModel table listing the countries v2 records may belong to.

Every v2 column that names a record's country references ``countries.id``, so
listing a new country takes a row, not a schema change. The two capability
flags say which calculations the country supports: a household-only country
has ``household_enabled`` set and ``society_wide_enabled`` unset.
"""

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class Country(SQLModel, table=True):
    """One country, its display name, and the calculations it supports.

    A society-wide country must also be household capable. A country that
    any record names cannot be deleted.
    """

    __tablename__ = "countries"
    __table_args__ = (
        sa.CheckConstraint(
            "household_enabled OR NOT society_wide_enabled",
            name="ck_countries_society_wide_requires_household",
        ),
    )

    id: str = Field(primary_key=True, max_length=2)
    name: str = Field(max_length=128)
    household_enabled: bool
    society_wide_enabled: bool
