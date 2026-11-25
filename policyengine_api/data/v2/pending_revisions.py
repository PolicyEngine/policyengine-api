"""Whether a v2 Alembic revision is still to be applied to a database.

The migration qualification commands check their own revision before they
count rows. Alembic's ``MigrationContext`` reads the database's current heads
from its version table through a Connection, so it gets the Session's own
connection and reads inside the Session's transaction (rule api.data.orm-only
names this exception).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

if TYPE_CHECKING:
    from sqlmodel import Session

V2_ALEMBIC_CONFIG = "alembic-v2.ini"


def v2_revision_is_pending(session: Session, revision: str) -> bool:
    """Return whether ``revision`` is in the upgrade path from the database's heads."""
    current_heads = MigrationContext.configure(session.connection()).get_current_heads()
    revisions = ScriptDirectory.from_config(
        Config(V2_ALEMBIC_CONFIG)
    ).iterate_revisions("heads", current_heads)
    return revision in {migration.revision for migration in revisions}
