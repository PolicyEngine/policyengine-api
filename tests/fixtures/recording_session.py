"""A session double that records every statement and write a connector issues."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from sqlalchemy.engine import make_url

from policyengine_api.data.v2.settings import POSTGRES_DRIVER

# Statements are compiled for the driver the v2 database engines must use, so
# they render as the application sends them, whichever SQLAlchemy is installed.
# ``postgresql.dialect()`` takes SQLAlchemy's default PostgreSQL driver instead,
# which is psycopg2 in SQLAlchemy 2.0 and psycopg in 2.1, and the two render
# different casts: psycopg casts string, integer and timestamp parameters too.
V2_DATABASE_DIALECT = make_url(f"{POSTGRES_DRIVER}://").get_dialect()()


@dataclass
class _ScriptedResult:
    """The scripted value a recorded statement returns, however it is read."""

    value: object

    def one_or_none(self) -> object:
        return self.value

    def scalar_one_or_none(self) -> object:
        return self.value


@dataclass
class RecordingSession:
    """Record statements (compiled for the v2 driver) and ORM writes, in order.

    Each ``exec`` or ``execute`` returns the next value from ``results``.
    """

    results: deque[object] = field(default_factory=deque)
    operations: list[tuple[object, ...]] = field(default_factory=list)

    def _record_statement(self, method: str, statement: object) -> _ScriptedResult:
        compiled = statement.compile(dialect=V2_DATABASE_DIALECT)
        self.operations.append((method, str(compiled), dict(compiled.params)))
        return _ScriptedResult(self.results.popleft())

    def exec(self, statement: object) -> _ScriptedResult:
        return self._record_statement("exec", statement)

    def execute(self, statement: object) -> _ScriptedResult:
        return self._record_statement("execute", statement)

    def add(self, instance: object) -> None:
        self.operations.append(("add", instance))

    def delete(self, instance: object) -> None:
        self.operations.append(("delete", instance))

    def flush(self) -> None:
        self.operations.append(("flush",))

    def refresh(self, instance: object) -> None:
        self.operations.append(("refresh", instance))
