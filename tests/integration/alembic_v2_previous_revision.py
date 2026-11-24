"""Check that a v2 revision still serves the API v1 release before it.

During a deploy the previous API v1 release runs beside the new revision.
``assert_revision_serves_previous_revision`` maps the parent revision's whole
schema with SQLAlchemy's automap, from what the database's Inspector
describes, upgrades, then runs that release's table usage through a Session on
those classes: every statement goes through the ORM (rule api.data.orm-only).

pytest rewrites only test modules' asserts, so each assert here carries the
value that explains its failure.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.automap import automap_base

from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.engine.interfaces import (
        ReflectedColumn,
        ReflectedForeignKeyConstraint,
    )
    from sqlalchemy.orm import Session, sessionmaker

ALEMBIC_VERSION_TABLE = "alembic_version"
USER_ASSOCIATION_TABLES = (
    "user_policies",
    "user_household_associations",
    "user_simulation_associations",
    "user_report_associations",
)
COUNTRY_COLUMN_NAMES = frozenset({"country", "country_id", "primary_country"})
# Nullable references that a parent-revision check constraint requires: a
# standard user's country, and one of each association's two references.
REFERENCES_REQUIRED_BY_CHECKS = frozenset(
    {
        ("simulations", "household_id"),
        ("users", "primary_country"),
        ("user_policies", "policy_id"),
        ("user_household_associations", "household_id"),
        ("user_simulation_associations", "simulation_id"),
        ("user_report_associations", "report_id"),
    }
)
# Required values that a parent-revision check constraint restricts.
CHECKED_VALUES = {("datasets", "year"): 2026}


@dataclass(frozen=True)
class RevisionTable:
    """One table at a revision: automap's class for it, and its description.

    ``columns``, ``primary_key`` and ``foreign_keys`` are what the database's
    Inspector described at that revision.
    """

    name: str
    model: Any
    columns: dict[str, ReflectedColumn]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ReflectedForeignKeyConstraint, ...]

    def primary_key_clause(self, row: Mapping[str, Any]) -> sa.ColumnElement[bool]:
        """Return the condition that selects ``row`` by its primary key."""
        return sa.and_(
            *(getattr(self.model, name) == row[name] for name in self.primary_key)
        )


def _map_no_relationships(*_arguments: object, **_options: object) -> None:
    """Tell automap to map no relationship between the tables' classes.

    The tests write rows with statements, and the database's foreign keys run
    the cascades.
    """


def _mapped_revision(sessions: sessionmaker[Session]) -> dict[str, RevisionTable]:
    """Map every public table at the database's current revision.

    Automap maps each table the Inspector describes to a class on a registry of
    its own. Alembic's version table is left out, and a referenced table
    comes before the tables that refer to it.
    """
    with sessions() as session:
        inspector = schema_inspector(session)
        revision_classes = automap_base()
        revision_classes.prepare(
            autoload_with=inspector, generate_relationship=_map_no_relationships
        )
        return {
            table_name: RevisionTable(
                name=table_name,
                model=revision_classes.classes[table_name],
                columns={
                    column["name"]: column
                    for column in inspector.get_columns(table_name)
                },
                primary_key=tuple(
                    inspector.get_pk_constraint(table_name)["constrained_columns"]
                ),
                foreign_keys=tuple(inspector.get_foreign_keys(table_name)),
            )
            for table_name, _foreign_keys in inspector.get_sorted_table_and_fkc_names()
            if table_name is not None and table_name != ALEMBIC_VERSION_TABLE
        }


def _is_required_without_default(column: ReflectedColumn) -> bool:
    return not column["nullable"] and column["default"] is None


def _new_required_columns(
    parent_table: RevisionTable, head_table: RevisionTable
) -> set[str]:
    return {
        column_name
        for column_name, column in head_table.columns.items()
        if column_name not in parent_table.columns
        and _is_required_without_default(column)
    }


def _string_test_value(column_type: sa.String, sequence: Iterator[int]) -> str:
    length = column_type.length or 255
    if length == 64:
        return uuid4().hex + uuid4().hex
    return f"value-{next(sequence)}"[:length]


# Checked in order: a column takes the value of the first type it is an
# instance of, so Enum, a String subclass, comes before String.
TYPED_TEST_VALUES: tuple[
    tuple[type[Any], Callable[[Any, Iterator[int]], object]], ...
] = (
    (sa.Enum, lambda column_type, _sequence: column_type.enums[0]),
    (sa.Uuid, lambda _column_type, _sequence: uuid4()),
    (sa.Boolean, lambda _column_type, _sequence: False),
    (sa.Integer, lambda _column_type, _sequence: 1),
    (sa.Float, lambda _column_type, _sequence: 0.0),
    # Later than every server-default created_at, as retention checks need.
    (
        sa.DateTime,
        lambda _column_type, _sequence: datetime.now(UTC) + timedelta(days=1),
    ),
    (sa.JSON, lambda _column_type, _sequence: {}),
    (sa.String, _string_test_value),
)


def _test_value(
    table_name: str, column: ReflectedColumn, sequence: Iterator[int]
) -> object:
    column_name = column["name"]
    if (table_name, column_name) in CHECKED_VALUES:
        return CHECKED_VALUES[(table_name, column_name)]
    if column_name in COUNTRY_COLUMN_NAMES:
        return "us"
    for column_type, test_value in TYPED_TEST_VALUES:
        if isinstance(column["type"], column_type):
            return test_value(column["type"], sequence)
    msg = f"no test value for {table_name}.{column_name}"
    raise AssertionError(msg)


def _row_values(
    table: RevisionTable,
    stored_rows: dict[str, dict[str, Any]],
    sequence: Iterator[int],
    *,
    head_table: RevisionTable | None = None,
) -> dict[str, Any]:
    """Supply only what the parent revision requires, plus check-bound values.

    ``head_table`` adds the columns head newly requires; only rows of the
    parent's read-only tables, which new code writes, may need them.
    """
    values = {
        column_name: _test_value(table.name, column, sequence)
        for column_name, column in table.columns.items()
        if _is_required_without_default(column)
        or (table.name, column_name) in REFERENCES_REQUIRED_BY_CHECKS
    }
    if head_table is not None:
        for column_name in _new_required_columns(table, head_table):
            values[column_name] = _test_value(
                head_table.name, head_table.columns[column_name], sequence
            )
    for foreign_key in table.foreign_keys:
        constrained_columns = foreign_key["constrained_columns"]
        if not any(column_name in values for column_name in constrained_columns):
            continue
        referenced_row = stored_rows[foreign_key["referred_table"]]
        for column_name, referred_column in zip(
            constrained_columns, foreign_key["referred_columns"], strict=True
        ):
            values[column_name] = referenced_row[referred_column]
    return values


def _insert_and_read_back(
    session: Session,
    table: RevisionTable,
    values: dict[str, Any],
    *,
    insert_table: RevisionTable | None = None,
) -> dict[str, Any]:
    """Insert a row, then read it back through the parent's mapped class.

    Rows of the parent's read-only tables are inserted through head's class,
    as only new code writes them.
    """
    target = insert_table if insert_table is not None else table
    session.execute(insert(target.model).values(values))
    # Selecting every column the parent's table has reads every column it maps.
    every_column = select(
        *(getattr(table.model, column_name) for column_name in table.columns)
    ).where(table.primary_key_clause(values))
    return dict(session.execute(every_column).mappings().one())


def _changed_row_count(session: Session, statement: sa.Update | sa.Delete) -> int:
    """Run an UPDATE or DELETE and return how many rows it changed."""
    return cast("CursorResult[Any]", session.execute(statement)).rowcount


def _rewrite_mapped_columns(
    session: Session, table: RevisionTable, row: dict[str, Any]
) -> None:
    """Update every non-key column the parent maps, as an ORM flush can."""
    key_columns = set(table.primary_key) | {
        column_name
        for foreign_key in table.foreign_keys
        for column_name in foreign_key["constrained_columns"]
    }
    rewritten = _changed_row_count(
        session,
        update(table.model)
        .where(table.primary_key_clause(row))
        .values(
            {
                # sa.null() keeps SQL NULL; a bare None becomes JSON null.
                name: sa.null() if value is None else value
                for name, value in row.items()
                if name not in key_columns
            }
        ),
    )
    assert rewritten == 1, table.name


@dataclass(frozen=True)
class PreviousRevisionSchemas:
    """A previous revision's mapped tables and those of the revision it was upgraded to.

    ``read_only_tables`` are the previous revision's tables that only new code
    writes, so their test rows are inserted through the upgraded table.
    """

    parent: dict[str, RevisionTable]
    head: dict[str, RevisionTable]
    read_only_tables: frozenset[str]

    def insert_table(self, table_name: str) -> RevisionTable | None:
        """Return the upgraded table for a read-only table, otherwise ``None``."""
        if table_name in self.read_only_tables:
            return self.head[table_name]
        return None


def _assert_user_deletion_cascades(
    session: Session,
    schemas: PreviousRevisionSchemas,
    stored_rows: dict[str, dict[str, Any]],
    sequence: Iterator[int],
) -> None:
    """Delete, through the parent's users class, a user who owns association rows."""
    parent, head = schemas.parent, schemas.head
    users = parent["users"]
    owner = _insert_and_read_back(
        session, users, _row_values(users, stored_rows, sequence)
    )
    owner_rows = {**stored_rows, "users": owner}
    for table_name in USER_ASSOCIATION_TABLES:
        table = parent[table_name]
        head_table = schemas.insert_table(table_name)
        _insert_and_read_back(
            session,
            table,
            _row_values(table, owner_rows, sequence, head_table=head_table),
            insert_table=head_table,
        )
    session.execute(
        insert(head["user_identities"].model).values(
            id=uuid4(),
            user_id=owner["id"],
            issuer="https://auth.example.test/",
            subject="google-oauth2|previous-revision",
        )
    )

    deleted = _changed_row_count(
        session, delete(users.model).where(users.model.id == owner["id"])
    )

    assert deleted == 1, users.name
    for table_name in (*USER_ASSOCIATION_TABLES, "user_identities"):
        model = head[table_name].model
        remaining = session.scalar(
            select(func.count()).select_from(model).where(model.user_id == owner["id"])
        )
        assert remaining == 0, table_name


def assert_revision_serves_previous_revision(
    sessions: sessionmaker[Session],
    previous_revision: str,
    revision: str,
    read_only_tables: frozenset[str],
) -> None:
    """Run a previous API v1 revision's table usage against ``revision``.

    The parent revision's schema is mapped and then used, after upgrading
    to ``revision``, the revision it ran beside during that deploy,
    to insert a row into every table it maps (supplying only what it
    requires), read the row back with every mapped column, rewrite those
    columns, delete it, and delete a user who owns association rows so the
    cascades run. ``revision`` may not give any table the parent revision
    writes a new required column without a server default; ``read_only_tables``
    are the parent's tables that only new code writes.
    """
    config = alembic_v2_config()

    try:
        command.downgrade(config, previous_revision)
        parent = _mapped_revision(sessions)
        command.upgrade(config, revision)
        head = _mapped_revision(sessions)
        parent_tables = list(parent.values())

        dropped_columns = sorted(
            f"{table.name}.{column_name}"
            for table in parent_tables
            for column_name in table.columns
            if table.name not in head or column_name not in head[table.name].columns
        )
        assert dropped_columns == [], dropped_columns
        tables_with_new_required_columns = {
            table.name: sorted(new_required_columns)
            for table in parent_tables
            if (new_required_columns := _new_required_columns(table, head[table.name]))
        }
        assert set(tables_with_new_required_columns) <= read_only_tables, (
            tables_with_new_required_columns
        )

        schemas = PreviousRevisionSchemas(parent, head, read_only_tables)
        sequence = itertools.count()
        with sessions() as session:
            try:
                stored_rows: dict[str, dict[str, Any]] = {}
                for table in parent_tables:
                    head_table = schemas.insert_table(table.name)
                    stored_rows[table.name] = _insert_and_read_back(
                        session,
                        table,
                        _row_values(
                            table, stored_rows, sequence, head_table=head_table
                        ),
                        insert_table=head_table,
                    )
                    _rewrite_mapped_columns(session, table, stored_rows[table.name])

                _assert_user_deletion_cascades(session, schemas, stored_rows, sequence)

                for table in reversed(parent_tables):
                    deleted = _changed_row_count(
                        session,
                        delete(table.model).where(
                            table.primary_key_clause(stored_rows[table.name])
                        ),
                    )
                    assert deleted == 1, table.name
            finally:
                session.rollback()
    finally:
        command.upgrade(config, "head")
