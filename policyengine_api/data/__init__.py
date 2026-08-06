"""Database package with lazy legacy exports.

Keeping package import side-effect free lets Alembic load model metadata without
opening Cloud SQL or creating a local database.
"""

from typing import Any


__all__ = ["PolicyEngineDatabase", "database", "local_database"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import data

        return getattr(data, name)
    raise AttributeError(name)
