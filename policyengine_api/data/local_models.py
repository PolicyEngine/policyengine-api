"""Declarative mappings for the temporary local SQLite cache only.

These tables are deliberately outside the production API v1 metadata and
Alembic lifecycle.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, JSON, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class LocalV1Base(DeclarativeBase):
    pass


class Tracer(LocalV1Base):
    __tablename__ = "tracers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    household_id: Mapped[int]
    policy_id: Mapped[int]
    country_id: Mapped[str] = mapped_column(String(3))
    api_version: Mapped[str] = mapped_column(String(10))
    tracer_output: Mapped[Any] = mapped_column(JSON)
