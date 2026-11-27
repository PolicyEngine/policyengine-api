"""Canonical SQLModel tables for saved reports published as public pages.

An author or admin publishes one of their saved reports as a public,
read-only page, linked by the saved report's ID. The page has its own
summary, authors, tags and content, and shows one succeeded run of the
report: each run it has shown is a version, and the newest is the one it
shows. API v1 writes both tables; nothing else reads them.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field, SQLModel

from policyengine_api.data.v2.models.base import IdentifiedModel, utc_now

# The longest card summary a page may have.
MAXIMUM_PUBLISHED_SUMMARY_LENGTH = 300


def _jsonb_type() -> sa.types.TypeEngine[Any]:
    # Typed JSON storage is one of the reviewed direct-SQLAlchemy exceptions.
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


class PublishedReport(SQLModel, table=True):
    """A saved report published as a public page, keyed by the saved report's ID.

    ``report_id`` is the report the saved report names, and the composite
    foreign key ``(user_report_id, report_id)`` to
    ``user_report_associations (id, report_id)`` holds it to that: deleting
    the saved report, or its owner's account, deletes the page, and the
    database refuses to repoint a published saved report to another report.
    ``summary``, ``author_ids`` (IDs from the website's ``authors.json``),
    ``tags`` (the website's topic and location tags) and ``content`` (an
    ordered list of Markdown and output-card blocks; a card left out is
    removed) are the page's own; one content serves every version.
    ``show_past_versions`` says whether readers may open earlier versions.
    """

    __tablename__ = "published_reports"
    __table_args__ = (
        # Named here: the naming convention's name is longer than PostgreSQL's
        # 63-character limit.
        sa.ForeignKeyConstraint(
            ["user_report_id", "report_id"],
            ["user_report_associations.id", "user_report_associations.report_id"],
            name="fk_published_reports_user_report_report",
            ondelete="CASCADE",
            onupdate="RESTRICT",
        ),
    )

    user_report_id: UUID = Field(primary_key=True)
    report_id: UUID
    summary: str = Field(max_length=MAXIMUM_PUBLISHED_SUMMARY_LENGTH)
    author_ids: list[str] = Field(sa_type=_jsonb_type())
    tags: list[str] = Field(sa_type=_jsonb_type())
    content: list[dict[str, Any]] = Field(sa_type=_jsonb_type())
    show_past_versions: bool = Field(
        default=False, sa_column_kwargs={"server_default": sa.false()}
    )
    # Kept as the base models declare them, without the base's ``id``: the
    # saved report's ID is this row's.
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_type=sa.DateTime(timezone=True),
        sa_column_kwargs={"server_default": sa.func.now()},
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_type=sa.DateTime(timezone=True),
        sa_column_kwargs={"server_default": sa.func.now(), "onupdate": sa.func.now()},
    )


class PublishedReportVersion(IdentifiedModel, table=True):
    """One run a published report has shown; the newest is the one it shows.

    A version names exactly one run: a report run of an economy or household
    report, or a budget-window run of a budget window. Its ``created_at`` is
    when the page moved to that run. A run a page has shown can't be
    deleted, and a page shows each run at most once. Deleting the page
    deletes its versions.
    """

    __tablename__ = "published_report_versions"
    __table_args__ = (
        sa.CheckConstraint(
            "(report_run_id IS NULL) <> (budget_window_run_id IS NULL)",
            name="ck_published_report_versions_one_run",
        ),
        sa.UniqueConstraint("user_report_id", "report_run_id"),
        # These two are named here: the naming convention's names are longer
        # than PostgreSQL's 63-character limit.
        sa.UniqueConstraint(
            "user_report_id",
            "budget_window_run_id",
            name="uq_published_report_versions_user_report_window_run",
        ),
        sa.ForeignKeyConstraint(
            ["budget_window_run_id"],
            ["budget_window_runs.id"],
            name="fk_published_report_versions_window_run_budget_window_runs",
            ondelete="RESTRICT",
        ),
    )

    user_report_id: UUID = Field(
        foreign_key="published_reports.user_report_id", ondelete="CASCADE"
    )
    report_run_id: UUID | None = Field(
        default=None,
        foreign_key="report_runs.id",
        ondelete="RESTRICT",
        index=True,
    )
    budget_window_run_id: UUID | None = Field(default=None, index=True)
