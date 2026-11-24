"""PostgreSQL objects and grants that the v2 privilege reconciliation reads.

The reconciliation reads grants on tables, views, materialized views and
sequences, grants on their columns, and default privileges (set by ``ALTER
DEFAULT PRIVILEGES``). The v2 schema has only tables, so tests make the rest
here: a view and a materialized view, mapped by ``PrivilegeTestView`` and
``PrivilegeTestMaterializedView`` so that the shared ``grant`` grants on them,
and sequences. The ORM has no form for these statements, so each helper that
writes SQL text is a ``no-orm-form`` exception of rule api.data.orm-only in
rules/registry.toml:

- ``grant_on_schema_object``: GRANT on a schema or a sequence, which the shared
  ``grant`` (tables, views and materialized views) doesn't cover;
- ``alter_default_privileges``: ALTER DEFAULT PRIVILEGES;
- ``create_view``: CREATE VIEW and CREATE MATERIALIZED VIEW, which SQLAlchemy
  has no construct for.

A test creates the objects as a temporary role, given CREATE on the schema.
``drop_role`` (``DROP OWNED BY``) then drops them, with the role's default
privileges.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from sqlalchemy import Sequence, text
from sqlalchemy.orm import registry
from sqlalchemy.schema import CreateSequence
from sqlmodel import Field, SQLModel

from tests.fixtures.database_sessions import schema_inspector

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SCHEMA = "public"
# The grantee that stands for every role, as GRANT and aclexplode name it.
PUBLIC_GRANTEE = "PUBLIC"
# A name the helpers write into a statement: lowercase letters, digits and _.
PLAIN_NAME = re.compile(r"[a-z_][a-z0-9_]*")
# A privilege list such as "SELECT", "USAGE, SELECT" or "CREATE".
PRIVILEGE_LIST = re.compile(r"[A-Z]+(?:, [A-Z]+)*")

SchemaObjectKind = Literal["SCHEMA", "SEQUENCE"]
DefaultObjectType = Literal["TABLES", "SEQUENCES"]


class _PrivilegeTestRelation(SQLModel, registry=registry()):
    """The base of the test views' classes, on a registry of their own."""


class PrivilegeTestView(_PrivilegeTestRelation, table=True):
    """The view ``create_view`` creates, of one row."""

    __tablename__ = "privilege_test_view"
    id: int = Field(primary_key=True)
    label: str


class PrivilegeTestMaterializedView(_PrivilegeTestRelation, table=True):
    """The materialized view ``create_view`` creates, of one row."""

    __tablename__ = "privilege_test_materialized_view"
    id: int = Field(primary_key=True)
    label: str


def _plain(name: str) -> str:
    if not PLAIN_NAME.fullmatch(name):
        msg = f"names here are lowercase letters, digits and _: {name!r}"
        raise ValueError(msg)
    return name


def _quoted(session: Session, name: str) -> str:
    quote = schema_inspector(session).dialect.identifier_preparer.quote
    quoted: str = quote(_plain(name))
    return quoted


def _grantee(session: Session, role: str) -> str:
    return PUBLIC_GRANTEE if role == PUBLIC_GRANTEE else _quoted(session, role)


def _privileges(privileges: str) -> str:
    if not PRIVILEGE_LIST.fullmatch(privileges):
        msg = f"not a privilege list: {privileges!r}"
        raise ValueError(msg)
    return privileges


def grant_on_schema_object(
    session: Session,
    privileges: str,
    *,
    object_kind: SchemaObjectKind,
    name: str,
    to: str,
) -> None:
    """Grant ``privileges`` on a schema, or a sequence in ``public``, to a role.

    ``to`` may be ``PUBLIC_GRANTEE``. For tables and views, use the shared
    ``grant``.
    """
    if object_kind == "SCHEMA":
        on_object = f"SCHEMA {_quoted(session, name)}"
    else:
        on_object = f"SEQUENCE {SCHEMA}.{_quoted(session, name)}"
    grantee = _grantee(session, to)
    session.execute(
        text(f"GRANT {_privileges(privileges)} ON {on_object} TO {grantee}")
    )


def alter_default_privileges(
    session: Session,
    *,
    creating_role: str,
    privileges: str,
    object_type: DefaultObjectType,
    to: str,
) -> None:
    """Give ``to`` the privileges on what ``creating_role`` creates in ``public``.

    ``to`` may be ``PUBLIC_GRANTEE``.
    """
    creator = _quoted(session, creating_role)
    grantee = _grantee(session, to)
    session.execute(
        text(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {creator} IN SCHEMA {SCHEMA} "
            f"GRANT {_privileges(privileges)} ON {object_type} TO {grantee}"
        )
    )


def create_view(
    session: Session,
    view: type[PrivilegeTestView | PrivilegeTestMaterializedView],
) -> None:
    """Create a test view of one row, ``id`` 1 and ``label`` text.

    ``PrivilegeTestMaterializedView`` is created as a materialized view.
    """
    view_kind = "MATERIALIZED VIEW" if view is PrivilegeTestMaterializedView else "VIEW"
    qualified_view = f"{SCHEMA}.{_quoted(session, view.__tablename__)}"
    session.execute(
        text(
            f"CREATE {view_kind} {qualified_view} "
            "AS SELECT 1 AS id, 'label'::text AS label"
        )
    )


def create_sequence(session: Session, name: str) -> None:
    """Create the sequence ``public.<name>``."""
    session.execute(CreateSequence(Sequence(_plain(name), schema=SCHEMA)))
