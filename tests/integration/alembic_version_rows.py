"""Read the revision Alembic recorded in a database, through a Session.

Alembic keeps the revision a database is at in its ``alembic_version`` table,
which has the same shape in API v1's MySQL database and the v2 PostgreSQL
database. The migration tests read it to check that a refused upgrade or
downgrade left the database where it was, through ``AlembicRevision``, the
table's mapped class on a registry of its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlmodel import col

from policyengine_api.data.v2.alembic_revision import AlembicRevision

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker


def current_revision(sessions: sessionmaker[Any]) -> str | None:
    """Return the revision the database is at, or None if it records none.

    It fails, as Alembic's ``MigrationContext.get_current_revision`` does, when
    the database records more than one revision.
    """
    with sessions() as session:
        revision: str | None = session.scalars(
            select(col(AlembicRevision.version_num))
        ).one_or_none()
    return revision
