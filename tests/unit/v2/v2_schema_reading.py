"""Read what the v2 models declare through the ORM, for the structural tests.

Rule api.data.orm-only keeps tests away from Core ``Table`` objects, so the
structural tests read the schema two ways:

- A model's columns come from its mapper (``model_columns``): the columns the
  model declares, with their types, defaults and nullability.
- Each table's keys, constraints and indexes come from an in-memory SQLite copy
  of the schema (``stored_v2_schema``), read with SQLAlchemy's Inspector, which
  reads what the database holds. SQLite keeps every name, column list, delete
  rule, check condition and index the models declare. Its columns also hold
  those a mapper leaves out (``exclude_properties``), such as a report run's
  four older cliff columns, which stay in the table until a revision drops them.

What only PostgreSQL receives, such as a partial index's PostgreSQL condition,
is read from the model's ``__table_args__`` (``declared_index``).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.orm import configure_mappers

from policyengine_api.data.v2.models import User
from tests.fixtures.database_sessions import (
    schema_inspector,
    sqlite_v1_sessions,
    sqlite_v2_sessions,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.engine import Inspector
    from sqlalchemy.engine.interfaces import ReflectedForeignKeyConstraint
    from sqlalchemy.orm import Mapper, Session
    from sqlalchemy.sql.base import ReadOnlyColumnCollection


@dataclass(frozen=True)
class StoredForeignKeyColumn:
    """One column of a stored foreign key, and the column it refers to."""

    column: str
    referred_table: str
    referred_column: str
    ondelete: str | None
    constraint_name: str | None

    @property
    def target(self) -> str:
        """Return the referred column as ``table.column``."""
        return f"{self.referred_table}.{self.referred_column}"


@dataclass(frozen=True)
class StoredForeignKey:
    """A stored foreign key: its name, columns, referred columns and delete rule."""

    name: str | None
    columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]
    ondelete: str | None

    @property
    def targets(self) -> tuple[str, ...]:
        """Return the referred columns, each as ``table.column``."""
        return tuple(
            f"{self.referred_table}.{column}" for column in self.referred_columns
        )

    @property
    def column_references(self) -> tuple[StoredForeignKeyColumn, ...]:
        """Return each of the key's columns with the column it refers to."""
        return tuple(
            StoredForeignKeyColumn(
                column=column,
                referred_table=self.referred_table,
                referred_column=referred_column,
                ondelete=self.ondelete,
                constraint_name=self.name,
            )
            for column, referred_column in zip(
                self.columns, self.referred_columns, strict=True
            )
        )


@dataclass(frozen=True)
class StoredColumn:
    """A stored column: its name, its type as the database reports it, and nulls."""

    name: str
    type: sa.types.TypeEngine[Any]
    nullable: bool


@dataclass(frozen=True)
class StoredIndex:
    """A stored index: its name, columns and whether it is unique."""

    name: str | None
    columns: tuple[str | None, ...]
    unique: bool


@dataclass(frozen=True)
class StoredTable:
    """A table as the database stores it: its columns, keys, constraints and indexes."""

    name: str
    columns: Mapping[str, StoredColumn]
    primary_key_name: str | None
    primary_key: tuple[str, ...]
    foreign_keys: tuple[StoredForeignKey, ...]
    unique_constraints: Mapping[str | None, tuple[str, ...]]
    checks: Mapping[str | None, str]
    indexes: Mapping[str | None, StoredIndex]

    @property
    def constraint_names(self) -> set[str | None]:
        """Return the names of the primary, foreign, unique and check constraints."""
        return {
            self.primary_key_name,
            *(foreign_key.name for foreign_key in self.foreign_keys),
            *self.unique_constraints,
            *self.checks,
        }

    @property
    def unique_column_sets(self) -> set[tuple[str, ...]]:
        """Return each unique constraint's columns."""
        return set(self.unique_constraints.values())

    @property
    def index_columns(self) -> dict[str | None, tuple[str | None, ...]]:
        """Return each index's columns, by the index's name."""
        return {name: index.columns for name, index in self.indexes.items()}

    @property
    def foreign_key_columns(self) -> tuple[StoredForeignKeyColumn, ...]:
        """Return every column of every foreign key with the column it refers to."""
        return tuple(
            reference
            for foreign_key in self.foreign_keys
            for reference in foreign_key.column_references
        )

    @property
    def references_by_column(self) -> dict[str, tuple[str, str | None]]:
        """Return each foreign key column's referred table and delete rule."""
        return {
            reference.column: (reference.referred_table, reference.ondelete)
            for reference in self.foreign_key_columns
        }

    def foreign_keys_of(self, column_name: str) -> tuple[StoredForeignKeyColumn, ...]:
        """Return the references from ``column_name``, one per foreign key it is in."""
        return tuple(
            reference
            for reference in self.foreign_key_columns
            if reference.column == column_name
        )

    def foreign_key(self, column_name: str) -> StoredForeignKeyColumn:
        """Return the one reference from ``column_name``."""
        (reference,) = self.foreign_keys_of(column_name)
        return reference

    def foreign_key_named(self, name: str) -> StoredForeignKey:
        """Return the foreign key called ``name``."""
        return next(
            foreign_key for foreign_key in self.foreign_keys if foreign_key.name == name
        )

    def foreign_keys_to(self, table_name: str) -> tuple[StoredForeignKey, ...]:
        """Return the foreign keys that refer to ``table_name``."""
        return tuple(
            foreign_key
            for foreign_key in self.foreign_keys
            if foreign_key.referred_table == table_name
        )


def _stored_foreign_key(reflected: ReflectedForeignKeyConstraint) -> StoredForeignKey:
    return StoredForeignKey(
        name=reflected["name"],
        columns=tuple(reflected["constrained_columns"]),
        referred_table=reflected["referred_table"],
        referred_columns=tuple(reflected["referred_columns"]),
        ondelete=reflected.get("options", {}).get("ondelete"),
    )


def _stored_table(inspector: Inspector, table_name: str) -> StoredTable:
    primary_key = inspector.get_pk_constraint(table_name)
    return StoredTable(
        name=table_name,
        columns={
            column["name"]: StoredColumn(
                name=column["name"],
                type=column["type"],
                nullable=bool(column["nullable"]),
            )
            for column in inspector.get_columns(table_name)
        },
        primary_key_name=primary_key["name"],
        primary_key=tuple(primary_key["constrained_columns"]),
        foreign_keys=tuple(
            _stored_foreign_key(foreign_key)
            for foreign_key in inspector.get_foreign_keys(table_name)
        ),
        unique_constraints={
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table_name)
        },
        checks={
            constraint["name"]: constraint["sqltext"]
            for constraint in inspector.get_check_constraints(table_name)
        },
        indexes={
            index["name"]: StoredIndex(
                name=index["name"],
                columns=tuple(index["column_names"]),
                unique=bool(index["unique"]),
            )
            for index in inspector.get_indexes(table_name)
        },
    )


def _stored_tables(session: Session) -> dict[str, StoredTable]:
    inspector = schema_inspector(session)
    return {
        table_name: _stored_table(inspector, table_name)
        for table_name in inspector.get_table_names()
    }


@cache
def stored_v2_schema() -> Mapping[str, StoredTable]:
    """Return every table of an in-memory SQLite copy of the v2 schema, by name."""
    with sqlite_v2_sessions() as sessions, sessions() as session:
        return _stored_tables(session)


def stored_v2_table(table_name: str) -> StoredTable:
    """Return the v2 table called ``table_name`` as SQLite stores it."""
    return stored_v2_schema()[table_name]


@cache
def stored_v1_schema() -> Mapping[str, StoredTable]:
    """Return every table of an in-memory SQLite copy of API v1's schema, by name."""
    with sqlite_v1_sessions() as sessions, sessions() as session:
        return _stored_tables(session)


def v2_mappers() -> tuple[Mapper[Any], ...]:
    """Return the mapper of every v2 model, once every mapper is configured."""
    configure_mappers()
    return tuple(sa.inspect(User).registry.mappers)


def v2_model(table_name: str) -> type[Any]:
    """Return the v2 model that maps the table called ``table_name``."""
    return next(
        mapper.class_
        for mapper in v2_mappers()
        if mapper.class_.__tablename__ == table_name
    )


def model_columns(model: type[Any] | str) -> ReadOnlyColumnCollection[str, Any]:
    """Return the columns a model's mapper maps, by name; a name means its v2 model."""
    mapped_class = v2_model(model) if isinstance(model, str) else model
    mapper: Mapper[Any] = sa.inspect(mapped_class)
    return mapper.columns


def declared_index(model: type[Any], index_name: str) -> sa.Index:
    """Return the index called ``index_name`` in the model's ``__table_args__``."""
    return next(
        argument
        for argument in model.__table_args__
        if isinstance(argument, sa.Index) and argument.name == index_name
    )
