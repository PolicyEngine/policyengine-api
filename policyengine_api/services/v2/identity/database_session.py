"""Transaction helpers for v2 identity provisioning."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import SessionTransaction
    from sqlmodel import Session


@contextmanager
def provisioning_savepoint(session: Session) -> Iterator[SessionTransaction]:
    """Contain one provisioning attempt so a lost race can be discarded.

    The caller rolls the yielded savepoint back when another request created
    the identity first; otherwise it is released when the block exits.
    """

    savepoint = session.begin_nested()
    try:
        yield savepoint
    except BaseException:
        if savepoint.is_active:
            savepoint.rollback()
        raise
    if savepoint.is_active:
        savepoint.commit()
