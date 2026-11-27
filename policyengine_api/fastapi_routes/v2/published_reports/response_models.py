"""Strict HTTP response models for v2 published reports."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from policyengine_api.fastapi_routes.v2.reports.response_models import (
    BudgetWindowReportItem,
    HouseholdReportItem,
    ReportItem,
    report_item,
)
from policyengine_api.fastapi_routes.v2.user_reports.response_models import (
    ReportProvisionItem,
    ReportValidationItem,
    SharedBaselineReformItem,
)
from policyengine_api.query_parameters import CountryId

if TYPE_CHECKING:
    from policyengine_api.services.v2.published_reports.types import (
        PublicationRead,
        PublishedReportRead,
    )


class StrictPublishedReportAPIModel(BaseModel):
    """Base for published-report responses; rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class MarkdownBlockItem(StrictPublishedReportAPIModel):
    """A section of Markdown the author wrote; render it without raw HTML."""

    type: Literal["markdown"]
    markdown: str


class OutputBlockItem(StrictPublishedReportAPIModel):
    """One of the report's output cards, by v3's key for it."""

    type: Literal["output"]
    output: str


ContentBlockItem = Annotated[
    MarkdownBlockItem | OutputBlockItem, Field(discriminator="type")
]


class PublicationVersionItem(StrictPublishedReportAPIModel):
    """One run the published report has shown.

    ``run_id`` is a report run's ID, or a budget window's budget-window
    run's. ``country_package_version`` and ``policyengine_version`` are the
    versions it ran on (a budget-window run's are its first year's, and none
    without a year), and ``published_at`` is when the page moved to it.
    """

    id: UUID
    run_id: UUID
    country_package_version: str | None
    policyengine_version: str | None
    published_at: datetime


class PublicationItem(StrictPublishedReportAPIModel):
    """A published report as its owner reads it, with every version, newest first.

    ``user_report_id`` is the saved report's ID, the published report's
    public link. The newest version is the one the page shows.
    ``published_at`` is when it was first published, and ``updated_at`` when
    any of it last changed.
    """

    user_report_id: UUID
    country_id: CountryId
    summary: str
    author_ids: list[str]
    tags: list[str]
    content: list[ContentBlockItem]
    show_past_versions: bool
    versions: list[PublicationVersionItem]
    published_at: datetime
    updated_at: datetime

    @classmethod
    def from_read(cls, read: PublicationRead) -> PublicationItem:
        """Build the item from the service's read."""
        return cls.model_validate(read)


class PublishedSavedReportItem(StrictPublishedReportAPIModel):
    """The saved report's presentation: as a shared report shows it, without IDs."""

    source_note: str | None
    provisions: list[ReportProvisionItem] | None
    validation: ReportValidationItem | None
    budget_window_years: int | None
    baseline_reform: SharedBaselineReformItem | None


class PublishedReportItem(StrictPublishedReportAPIModel):
    """A published report as anyone reads it, without its owner.

    ``id`` is the saved report's ID, the page's link, and ``title`` the saved
    report's name. ``version`` is the version read, and ``report`` the report
    with that version's run, as ``GET /v2/reports/{id}?run_id=`` answers it,
    labelled with the title. ``versions`` lists the versions a reader may
    open, newest first: every version while ``show_past_versions``, else
    only the newest.
    """

    id: UUID
    country_id: CountryId
    title: str | None
    summary: str
    author_ids: list[str]
    tags: list[str]
    content: list[ContentBlockItem]
    show_past_versions: bool
    saved_report: PublishedSavedReportItem
    version: PublicationVersionItem
    versions: list[PublicationVersionItem]
    published_at: datetime
    updated_at: datetime
    report: Annotated[
        ReportItem | HouseholdReportItem | BudgetWindowReportItem,
        Field(discriminator="kind"),
    ]

    @classmethod
    def from_read(cls, read: PublishedReportRead) -> PublishedReportItem:
        """Build the item from the service's read, with its report's item."""
        return cls.model_validate(
            {
                "id": read.id,
                "country_id": read.country_id,
                "title": read.title,
                "summary": read.summary,
                "author_ids": read.author_ids,
                "tags": read.tags,
                "content": read.content,
                "show_past_versions": read.show_past_versions,
                "saved_report": PublishedSavedReportItem.model_validate(
                    read.saved_report
                ),
                "version": PublicationVersionItem.model_validate(read.version),
                "versions": [
                    PublicationVersionItem.model_validate(version)
                    for version in read.versions
                ],
                "published_at": read.published_at,
                "updated_at": read.updated_at,
                "report": report_item(read.report),
            }
        )


ResultT = TypeVar("ResultT")


class PublishedReportSuccessResponse(StrictPublishedReportAPIModel, Generic[ResultT]):
    """Success envelope: ``status`` "ok", a null ``message`` and the ``result``."""

    status: Literal["ok"] = "ok"
    message: None = None
    result: ResultT


class PublicationDetailResult(StrictPublishedReportAPIModel):
    """Result holding the owner's published report in ``item``."""

    item: PublicationItem


class PublishedReportDetailResult(StrictPublishedReportAPIModel):
    """Result holding a published report in ``item``."""

    item: PublishedReportItem


class PublicationDetailResponse(
    PublishedReportSuccessResponse[PublicationDetailResult]
):
    """Success response holding the owner's published report."""


class PublishedReportDetailResponse(
    PublishedReportSuccessResponse[PublishedReportDetailResult]
):
    """Success response holding a published report."""
