"""``parameter_values`` as the revisions before 1c651058fac5 leave it.

Until revision 1c651058fac5 the table has ``dynamic_id``, a dynamic's values
were stored in it (until revision 7f7335f0eb31 moved them to
``dynamic_parameter_values``), and the downgrade through 7f7335f0eb31 copies
them back. ``ParameterValue`` no longer maps the column, so tests of those
revisions store and read such rows through this class, on a registry of its
own. No code creates a table from it: Alembic creates the table.
"""

# No ``from __future__ import annotations``: SQLAlchemy reads the class's
# ``Mapped`` annotations when it maps it, so their names stay imported at
# runtime.
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, registry

parameter_values_with_dynamics = registry()


@parameter_values_with_dynamics.mapped
class ParameterValueWithDynamic:
    """A ``parameter_values`` row with the ``dynamic_id`` it had before 1c651058fac5.

    ``created_at`` is filled in by the database when an insert leaves it out.
    """

    __tablename__ = "parameter_values"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parameter_id: Mapped[UUID]
    value_json: Mapped[Any] = mapped_column(postgresql.JSONB)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    policy_id: Mapped[UUID | None]
    dynamic_id: Mapped[UUID | None]
