"""Conversions between published-report rows, inputs and reads."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from policyengine_api.services.v2.published_reports.types import (
    PublicationRead,
    PublicationVersionRead,
    PublishedReportRead,
    PublishedRun,
    PublishedSavedReportRead,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from policyengine_api.data.v2.models import (
        PublishedReport,
        PublishedReportVersion,
        ReportRun,
    )
    from policyengine_api.services.v2.published_reports.types import (
        PublicationFields,
        PublicationUpdateInput,
        ShownVersions,
    )
    from policyengine_api.services.v2.stored_reports.types import (
        ReportKind,
        StoredReportRead,
    )
    from policyengine_api.services.v2.user_reports.types import SharedUserReportRead


def _aware(moment: datetime) -> datetime:
    """Return a stored time in UTC; SQLite returns it without its zone."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def publication_values(fields: PublicationFields) -> dict[str, Any]:
    """Return a published report's column values from an author's fields."""
    return {
        "summary": fields.summary,
        "author_ids": list(fields.author_ids),
        "tags": list(fields.tags),
        "content": [block.model_dump() for block in fields.content],
        "show_past_versions": fields.show_past_versions,
    }


def publication_update_values(edit: PublicationUpdateInput) -> dict[str, Any]:
    """Return the column values an edit sets: the fields it sends."""
    values = edit.model_dump(include=edit.model_fields_set)
    if "content" in values:
        values["content"] = [block.model_dump() for block in edit.content or []]
    return values


def published_run(kind: ReportKind, run_id: UUID) -> PublishedRun:
    """Return the run a version shows: a budget window's is a budget-window run."""
    if kind == "budget_window":
        return PublishedRun(budget_window_run_id=run_id)
    return PublishedRun(report_run_id=run_id)


def publication_version_read(
    version: PublishedReportVersion,
    report_run: ReportRun | None,
    window_first_years: Mapping[UUID, ReportRun],
) -> PublicationVersionRead:
    """Return a version with its run's versions.

    A report run's are its own; a budget-window run's are its first year's,
    or none for a window run with no year.
    """
    run_id = version.report_run_id or version.budget_window_run_id
    if run_id is None:
        msg = f"Published report version {version.id} names no run"
        raise ValueError(msg)
    versions_run = (
        report_run
        if version.budget_window_run_id is None
        else window_first_years.get(version.budget_window_run_id)
    )
    return PublicationVersionRead(
        id=version.id,
        run_id=run_id,
        country_package_version=(
            None if versions_run is None else versions_run.country_package_version
        ),
        policyengine_version=(
            None if versions_run is None else versions_run.policyengine_version
        ),
        published_at=_aware(version.created_at),
    )


def publication_read(
    publication: PublishedReport,
    *,
    country_id: str,
    versions: Sequence[PublicationVersionRead],
) -> PublicationRead:
    """Return the published report as its owner reads it."""
    return PublicationRead(
        user_report_id=publication.user_report_id,
        country_id=country_id,
        summary=publication.summary,
        author_ids=list(publication.author_ids),
        tags=list(publication.tags),
        content=list(publication.content),
        show_past_versions=publication.show_past_versions,
        versions=tuple(versions),
        published_at=_aware(publication.created_at),
        updated_at=_aware(publication.updated_at),
    )


def published_saved_report_read(
    shared: SharedUserReportRead,
) -> PublishedSavedReportRead:
    """Return the shared view's presentation fields a published report shows."""
    return PublishedSavedReportRead(
        source_note=shared.source_note,
        provisions=shared.provisions,
        validation=shared.validation,
        budget_window_years=shared.budget_window_years,
        baseline_reform=shared.baseline_reform,
    )


def published_report_read(
    page: PublicationRead,
    *,
    title: str | None,
    saved_report: PublishedSavedReportRead,
    shown: ShownVersions,
    report: StoredReportRead,
) -> PublishedReportRead:
    """Return the published report as anyone reads it.

    The report is labelled with the page's title, and shows none of the
    owner's notes.
    """
    return PublishedReportRead(
        id=page.user_report_id,
        country_id=page.country_id,
        title=title,
        summary=page.summary,
        author_ids=page.author_ids,
        tags=page.tags,
        content=page.content,
        show_past_versions=page.show_past_versions,
        saved_report=saved_report,
        version=shown.version,
        versions=shown.readable,
        published_at=page.published_at,
        updated_at=page.updated_at,
        report=replace(report, label=title, description=None),
    )
