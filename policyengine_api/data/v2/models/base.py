"""Shared non-table SQLModel fields for the reviewed v2 schema."""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


# These are the complete direct-SQLAlchemy categories permitted in the v2
# table layer. Each remains underneath canonical SQLModel table classes and
# Field/Relationship declarations; no parallel declarative model exists.
DIRECT_SQLALCHEMY_EXCEPTIONS = MappingProxyType(
    {
        "timezone_aware_timestamps": (
            "SQLModel Field has no first-class TIMESTAMP WITH TIME ZONE and "
            "server-default/on-update parameters."
        ),
        "named_enums": (
            "Postgres enum type names and value serialization require an "
            "explicit SQLAlchemy Enum supplied through Field(sa_type=...)."
        ),
        "typed_json_and_text": (
            "JSON and unbounded text storage require explicit SQLAlchemy "
            "types while remaining SQLModel Fields."
        ),
        "named_constraints_and_indexes": (
            "Composite uniqueness and foreign keys, database checks, and "
            "multi-column indexes are not expressible by one SQLModel Field."
        ),
        "ambiguous_foreign_key_relationships": (
            "Dataset input/output, baseline/reform, and overlapping composite "
            "region-default joins need SQLAlchemy relationship hints exposed "
            "by SQLModel Relationship."
        ),
        "transaction_conflict_recovery": (
            "Concurrent report idempotency requires a savepoint and bounded "
            "IntegrityError recovery around the database uniqueness constraint."
        ),
    }
)


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-created rows."""

    return datetime.now(timezone.utc)


class IdentifiedModel(SQLModel):
    """Non-table UUID and creation timestamp fields."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # SQLModel has no dedicated timezone-aware timestamp option. The local
    # SQLAlchemy type keeps Postgres TIMESTAMP WITH TIME ZONE while Field
    # remains the canonical column declaration surface.
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_type=sa.DateTime(timezone=True),
        sa_column_kwargs={"server_default": sa.func.now()},
    )


class TimestampedModel(IdentifiedModel):
    """Non-table UUID plus creation/update timestamp fields."""

    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_type=sa.DateTime(timezone=True),
        sa_column_kwargs={
            "server_default": sa.func.now(),
            "onupdate": sa.func.now(),
        },
    )


def enum_type(enum_class: type, name: str) -> sa.Enum:
    """Build a stable lowercase-value Postgres enum for a string Enum."""

    # Native named enums and value serialization are SQLAlchemy features that
    # SQLModel intentionally exposes through Field(sa_type=...).
    return sa.Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
    )
