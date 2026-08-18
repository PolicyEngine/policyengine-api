"""Bounded Alembic operations and comparators for declared v2 reference rows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from alembic.autogenerate import comparators, renderers
from alembic.operations import MigrateOperation, Operations, ops
import sqlalchemy as sa

from policyengine_api.data.v2.reference_data import REFERENCE_DATA, ReferenceTable
from policyengine_api.data.v2.table_inventory import EXPECTED_V2_TABLES


class ReferenceDataMigrationError(RuntimeError):
    """Raised when a declared row change cannot be applied or reversed safely."""


def _ordered(values: dict[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    return {key: values[key] for key in sorted(values)}


@Operations.register_operation("v2_reference_row_change")
class ReferenceRowChangeOp(MigrateOperation):
    """One deterministic and reversible declared-row transition."""

    def __init__(
        self,
        table_name: str,
        *,
        key: dict[str, Any],
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        if table_name not in EXPECTED_V2_TABLES:
            raise ReferenceDataMigrationError(
                f"reference-data operation targets unreviewed table {table_name}"
            )
        if not key or (before is None and after is None):
            raise ReferenceDataMigrationError(
                "reference-data operations need a stable key and one row state"
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

    def reverse(self) -> "ReferenceRowChangeOp":
        return ReferenceRowChangeOp(
            self.table_name,
            key=self.key,
            before=self.after,
            after=self.before,
        )

    def to_diff_tuple(self) -> tuple[Any, ...]:
        """Expose deterministic drift details to ``alembic check``."""

        return (
            "v2_reference_row_change",
            self.table_name,
            self.key,
            self.before,
            self.after,
        )


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
            raise ReferenceDataMigrationError(
                f"{table_name} insert found an existing managed row"
            )
        return
    if current is None or any(
        current.get(column) != _normalize(value) for column, value in expected.items()
    ):
        raise ReferenceDataMigrationError(
            f"{table_name} row differs from the generated before state"
        )


def _assert_after(
    current: dict[str, Any] | None,
    expected: dict[str, Any] | None,
    *,
    table_name: str,
) -> None:
    if expected is None:
        if current is not None:
            raise ReferenceDataMigrationError(
                f"{table_name} generated delete left the managed row present"
            )
        return
    if current is None or any(
        current.get(column) != _normalize(value) for column, value in expected.items()
    ):
        raise ReferenceDataMigrationError(
            f"{table_name} row differs from the generated after state"
        )


@Operations.implementation_for(ReferenceRowChangeOp)
def _apply_reference_row_change(
    operations: Operations,
    operation: ReferenceRowChangeOp,
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


@renderers.dispatch_for(ReferenceRowChangeOp)
def _render_reference_row_change(
    autogen_context, operation: ReferenceRowChangeOp
) -> str:
    return (
        "op.v2_reference_row_change("
        f"{operation.table_name!r}, key={operation.key!r}, "
        f"before={operation.before!r}, after={operation.after!r})"
    )


def _managed_rows(
    connection: sa.Connection,
    declaration: ReferenceTable,
) -> dict[tuple[Any, ...], dict[str, Any]]:
    table = sa.Table(
        declaration.table_name,
        sa.MetaData(),
        schema="public",
        autoload_with=connection,
    )
    prefix_column = table.c[declaration.managed_prefix_column]
    rows = connection.execute(
        sa.select(table).where(prefix_column.startswith(declaration.managed_prefix))
    ).mappings()
    return {
        tuple(_normalize(row[column]) for column in declaration.key_columns): {
            column: _normalize(value) for column, value in row.items()
        }
        for row in rows
    }


def _table_differences(
    connection: sa.Connection,
    declaration: ReferenceTable,
) -> tuple[list[ReferenceRowChangeOp], list[ReferenceRowChangeOp]]:
    live = _managed_rows(connection, declaration)
    desired = {
        tuple(row.key[column] for column in declaration.key_columns): row
        for row in declaration.rows
    }
    removals: list[ReferenceRowChangeOp] = []
    upserts: list[ReferenceRowChangeOp] = []

    for stable_key in sorted(live):
        if stable_key not in desired:
            key = dict(zip(declaration.key_columns, stable_key))
            removals.append(
                ReferenceRowChangeOp(
                    declaration.table_name,
                    key=key,
                    before=live[stable_key],
                    after=None,
                )
            )

    for stable_key in sorted(desired):
        row = desired[stable_key]
        desired_values = row.complete_values
        current = live.get(stable_key)
        if current is None:
            upserts.append(
                ReferenceRowChangeOp(
                    declaration.table_name,
                    key=dict(row.key),
                    before=None,
                    after=desired_values,
                )
            )
            continue
        tracked_current = {column: current.get(column) for column in desired_values}
        if tracked_current != desired_values:
            upserts.append(
                ReferenceRowChangeOp(
                    declaration.table_name,
                    key=dict(row.key),
                    before=tracked_current,
                    after=desired_values,
                )
            )
    return removals, upserts


@comparators.dispatch_for("schema")
def compare_reference_data(autogen_context, upgrade_ops, _schemas) -> None:
    """Append declared row drift after the complete schema already exists."""

    connection = autogen_context.connection
    if connection is None:
        return
    live_tables = set(sa.inspect(connection).get_table_names(schema="public"))
    # Keep the clean schema baseline separate. The next autogeneration, after
    # baseline upgrade, observes all tables and emits the data-only revision.
    if not EXPECTED_V2_TABLES.issubset(live_tables):
        return

    differences = [
        _table_differences(connection, declaration) for declaration in REFERENCE_DATA
    ]
    # Delete children before parents; insert/update parents before children.
    removals = [
        operation
        for table_removals, _ in reversed(differences)
        for operation in table_removals
    ]
    upserts = [
        operation for _, table_upserts in differences for operation in table_upserts
    ]
    upgrade_ops.ops.extend([*removals, *upserts])


def _is_destructive(operation: MigrateOperation) -> bool:
    if isinstance(operation, (ops.DropTableOp, ops.DropColumnOp)):
        return True
    if isinstance(operation, ops.ModifyTableOps):
        return any(_is_destructive(child) for child in operation.ops)
    return False


def order_generated_operations(_context, _revision, directives) -> None:
    """Place data changes after schema additions and before destructive DDL."""

    for script in directives:
        operations = script.upgrade_ops.ops
        data = [op for op in operations if isinstance(op, ReferenceRowChangeOp)]
        non_data = [op for op in operations if not isinstance(op, ReferenceRowChangeOp)]
        constructive = [op for op in non_data if not _is_destructive(op)]
        destructive = [op for op in non_data if _is_destructive(op)]
        script.upgrade_ops.ops = [*constructive, *data, *destructive]
        script.downgrade_ops.ops = [
            operation.reverse() for operation in reversed(script.upgrade_ops.ops)
        ]
