"""Execute row operations already embedded in immutable v2 Alembic revisions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from alembic.operations import MigrateOperation, Operations
import sqlalchemy as sa


HISTORICAL_REFERENCE_TABLES = frozenset(
    {"tax_benefit_models", "tax_benefit_model_versions"}
)


class HistoricalDataMigrationError(RuntimeError):
    """Raised when an immutable row transition cannot be replayed safely."""


def _ordered(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    return {key: values[key] for key in sorted(values)}


@Operations.register_operation("v2_reference_row_change")
class HistoricalReferenceRowChangeOp(MigrateOperation):
    """One guarded row transition embedded in the historical v2 chain."""

    def __init__(
        self,
        table_name: str,
        *,
        key: dict[str, Any],
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        if table_name not in HISTORICAL_REFERENCE_TABLES:
            raise HistoricalDataMigrationError(
                f"historical data operation targets unreviewed table {table_name}"
            )
        if not key or (before is None and after is None):
            raise HistoricalDataMigrationError(
                "historical data operations need a stable key and one row state"
            )
        self.table_name = table_name
        self.key = _ordered(key) or {}
        self.before = _ordered(before)
        self.after = _ordered(after)

    @classmethod
    def v2_reference_row_change(
        cls,
        operations: Operations,
        table_name: str,
        *,
        key: dict[str, Any],
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> Any:
        return operations.invoke(cls(table_name, key=key, before=before, after=after))


def _normalize(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_normalize(item) for item in value]
    return value


def _coerce(column: sa.Column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, sa.Uuid) and not isinstance(value, UUID):
        return UUID(str(value))
    if isinstance(column.type, sa.DateTime) and not isinstance(value, datetime):
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return value


def _predicate(table: sa.Table, key: dict[str, Any]) -> sa.ColumnElement:
    return sa.and_(
        *(
            table.c[column] == _coerce(table.c[column], value)
            for column, value in key.items()
        )
    )


def _current_row(
    bind: sa.Connection,
    table: sa.Table,
    key: dict[str, Any],
) -> dict[str, Any] | None:
    row = (
        bind.execute(sa.select(table).where(_predicate(table, key)))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return {column: _normalize(value) for column, value in row.items()}


def _assert_before(
    current: dict[str, Any] | None,
    expected: dict[str, Any] | None,
    *,
    table_name: str,
) -> None:
    if expected is None:
        if current is not None:
            raise HistoricalDataMigrationError(
                f"{table_name} insert found an existing historical row"
            )
        return
    if current is None or any(
        current.get(column) != _normalize(value) for column, value in expected.items()
    ):
        raise HistoricalDataMigrationError(
            f"{table_name} row differs from the historical before state"
        )


def _assert_after(
    current: dict[str, Any] | None,
    expected: dict[str, Any] | None,
    *,
    table_name: str,
) -> None:
    if expected is None:
        if current is not None:
            raise HistoricalDataMigrationError(
                f"{table_name} historical delete left the row present"
            )
        return
    if current is None or any(
        current.get(column) != _normalize(value) for column, value in expected.items()
    ):
        raise HistoricalDataMigrationError(
            f"{table_name} row differs from the historical after state"
        )


@Operations.implementation_for(HistoricalReferenceRowChangeOp)
def _apply_historical_reference_row_change(
    operations: Operations,
    operation: HistoricalReferenceRowChangeOp,
) -> None:
    bind = operations.get_bind()
    table = sa.Table(
        operation.table_name,
        sa.MetaData(),
        schema="public",
        autoload_with=bind,
    )
    current = _current_row(bind, table, operation.key)
    _assert_before(current, operation.before, table_name=operation.table_name)

    if operation.after is None:
        bind.execute(table.delete().where(_predicate(table, operation.key)))
    elif operation.before is None:
        values = {
            column: _coerce(table.c[column], value)
            for column, value in operation.after.items()
        }
        bind.execute(table.insert().values(**values))
    else:
        values = {
            column: _coerce(table.c[column], value)
            for column, value in operation.after.items()
            if column not in operation.key
        }
        bind.execute(
            table.update().where(_predicate(table, operation.key)).values(**values)
        )

    _assert_after(
        _current_row(bind, table, operation.key),
        operation.after,
        table_name=operation.table_name,
    )
