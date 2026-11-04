"""Proof fixture: a query through a SQLAlchemy session. The rule must accept it.

The connection comes from a SQLAlchemy engine and session, and the tables come
from Alembic revisions applied before the application starts, so this module
neither imports a database driver nor changes the schema.
"""

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.data.v1_models import UserProfile


def read_current_role(session_factory: sessionmaker[Session]) -> str:
    """Return the role the database authenticated, through a SQLAlchemy session."""
    with session_factory() as session:
        return str(session.execute(text("SELECT current_user")).scalar_one())


def count_user_profiles(session_factory: sessionmaker[Session]) -> int:
    """Count user profiles in the table an Alembic revision created."""
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(UserProfile)) or 0
