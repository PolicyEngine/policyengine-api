"""Schema-only declarations of the v2 columns a later revision drops.

The simulation and report association tables still have the pre-Stage 12A
``country`` and ``label`` columns. They stay in the database until a later v2
revision drops them. That revision runs while this release serves traffic, so
this release must never read or write them.

They stay declared here only so the v2 metadata keeps matching the schema:
``alembic check`` and the migration environment's head-schema validation
compare the two. They are plain SQLAlchemy columns that no model maps, so no
ORM query, insert or update reaches them. Nothing imports this module except
the models package, which registers it. Deleting it is what makes
autogeneration produce the revision that drops them.
"""

from sqlalchemy import Column, String
from sqlmodel import SQLModel

from policyengine_api.data.v2.models.associations import (
    UserReportAssociation,
    UserSimulationAssociation,
)

METADATA = SQLModel.metadata

# The retired association columns, by table, with their string lengths.
RETIRED_ASSOCIATION_COLUMNS = {
    UserSimulationAssociation.__tablename__: {"country": 16, "label": 255},
    UserReportAssociation.__tablename__: {"country": 16, "label": 255},
}


def _declare_retired_association_columns() -> None:
    """Add the retired columns to the association tables, but not their models.

    The association models no longer declare these columns, so their mappers
    never select, insert or update them: a column appended to a table after
    its mapper exists stays unmapped.
    """
    for table_name, columns in RETIRED_ASSOCIATION_COLUMNS.items():
        for column_name, length in columns.items():
            METADATA.tables[table_name].append_column(
                Column(column_name, String(length), nullable=True)
            )


_declare_retired_association_columns()
