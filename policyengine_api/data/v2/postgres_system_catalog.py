"""Mapped classes of the PostgreSQL system catalog tables the reconciliation reads.

PostgreSQL owns these tables and views, in its ``pg_catalog`` schema, which every
search path includes. Each class names only the columns the reconciliation
reads and a key, and is only ever read. They are SQLModel classes on a registry
of their own, so they stay out of ``V2_METADATA``, which Alembic compares with
the v2 schema. The access control lists (PostgreSQL's ``aclitem[]``) are never
read as values, only passed to ``aclexplode``, which returns one row per entry.
"""

from __future__ import annotations

from sqlalchemy import Boolean, SmallInteger, String
from sqlalchemy.dialects.postgresql import OID
from sqlalchemy.orm import registry
from sqlalchemy.types import UserDefinedType
from sqlmodel import Field, SQLModel


class AccessControlList(UserDefinedType[list[str]]):
    """PostgreSQL's ``aclitem[]``, which SQLAlchemy has no type for.

    The lists are only passed to ``aclexplode``, never read as values.
    """

    cache_ok = True

    def get_col_spec(self, **_options: object) -> str:
        """Name the type as PostgreSQL does."""
        return "aclitem[]"


class PostgresSystemCatalogTable(SQLModel, registry=registry()):
    """The base of the system catalog classes, on a registry of their own."""


class PgNamespace(PostgresSystemCatalogTable, table=True):
    """A schema."""

    __tablename__ = "pg_namespace"

    oid: int = Field(sa_type=OID, primary_key=True)
    nspname: str = Field(sa_type=String)


class PgClass(PostgresSystemCatalogTable, table=True):
    """A table or a table-like object, such as a view or a sequence."""

    __tablename__ = "pg_class"

    oid: int = Field(sa_type=OID, primary_key=True)
    relname: str = Field(sa_type=String)
    relnamespace: int = Field(sa_type=OID)
    relkind: str = Field(sa_type=String)
    relacl: list[str] | None = Field(default=None, sa_type=AccessControlList)


class PgAttribute(PostgresSystemCatalogTable, table=True):
    """A column of a table, numbered from 1; system columns are below zero."""

    __tablename__ = "pg_attribute"

    attrelid: int = Field(sa_type=OID, primary_key=True)
    attnum: int = Field(sa_type=SmallInteger, primary_key=True)
    attname: str = Field(sa_type=String)
    attisdropped: bool = Field(sa_type=Boolean)
    attacl: list[str] | None = Field(default=None, sa_type=AccessControlList)


class PgRoles(PostgresSystemCatalogTable, table=True):
    """A role (the ``pg_roles`` view of ``pg_authid``, readable by every role)."""

    __tablename__ = "pg_roles"

    oid: int = Field(sa_type=OID, primary_key=True)
    rolname: str = Field(sa_type=String)


class PgDefaultAcl(PostgresSystemCatalogTable, table=True):
    """The privileges a role's new objects of one type get, in one schema or all."""

    __tablename__ = "pg_default_acl"

    oid: int = Field(sa_type=OID, primary_key=True)
    defaclrole: int = Field(sa_type=OID)
    defaclnamespace: int = Field(sa_type=OID)
    defaclobjtype: str = Field(sa_type=String)
    defaclacl: list[str] | None = Field(default=None, sa_type=AccessControlList)
