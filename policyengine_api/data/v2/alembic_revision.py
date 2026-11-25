"""A read-only mapped class of Alembic's own revision table, ``alembic_version``.

Alembic creates and writes the table: one row per head revision the database
is at, in its ``version_num`` column. Code reads it through ``AlembicRevision``,
as catalog publication does to check the v2 database's revision before it
writes anything, and never writes it.

``AlembicRevision`` is on a registry of its own, on neither the v2 metadata
(``V2_METADATA``) nor the publication staging tables' registry, so Alembic never
compares it with the database and no ``create_all`` creates it. It names only
the table and its primary-key column, which API v1's MySQL database and the v2
PostgreSQL database share.
"""

from sqlalchemy.orm import registry
from sqlmodel import Field, SQLModel

ALEMBIC_REVISION_TABLE = "alembic_version"


class AlembicRevisionBase(SQLModel, registry=registry()):
    """The declarative base of ``AlembicRevision``, on a registry of its own."""


class AlembicRevision(AlembicRevisionBase, table=True):
    """One head revision Alembic recorded in ``alembic_version``. Read it only."""

    __tablename__ = ALEMBIC_REVISION_TABLE

    version_num: str = Field(primary_key=True, max_length=32)
