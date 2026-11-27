"""Framework-independent data exchanged by the v2 published-report layers.

A published report is a saved report its author published as a public
page. The page has a summary, authors, tags and content of its own, and
shows one succeeded run of the saved report's report: each run it has
shown is a version, and the newest is the one it shows. Authors are IDs
from the website's ``authors.json`` and tags the website's topic and
location tags, both lower-case words joined by hyphens, checked for form
only. The content is an ordered list of Markdown blocks and output-card
blocks; a card is named by a key v3 defines, and a card left out is
removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

from policyengine_api.data.v2.models.published_reports import (
    MAXIMUM_PUBLISHED_SUMMARY_LENGTH,
)
from policyengine_api.query_parameters import ResourceId

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.stored_reports.types import StoredReportRead
    from policyengine_api.services.v2.user_reports.types import (
        SharedBaselineReformRead,
        StoredJSONObject,
    )

MAXIMUM_PUBLISHED_AUTHORS = 10
MAXIMUM_PUBLISHED_TAGS = 20
MAXIMUM_CONTENT_BLOCKS = 100
MAXIMUM_MARKDOWN_LENGTH = 20_000
MAXIMUM_NAME_LENGTH = 64

# An author or tag ID as the website writes them: lower-case letters and
# digits in words joined by single hyphens, such as ``nikhil-woodruff``.
WebsiteId = Annotated[
    str,
    StringConstraints(
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=MAXIMUM_NAME_LENGTH
    ),
]
# An output card's key as v3 names it, such as ``budgetary_impact``.
OutputKey = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=MAXIMUM_NAME_LENGTH),
]
PublishedSummary = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAXIMUM_PUBLISHED_SUMMARY_LENGTH),
]
AuthorIds = Annotated[
    list[WebsiteId], Field(min_length=1, max_length=MAXIMUM_PUBLISHED_AUTHORS)
]
Tags = Annotated[list[WebsiteId], Field(max_length=MAXIMUM_PUBLISHED_TAGS)]


class StrictPublicationModel(BaseModel):
    """Reject fields outside the published-report contract."""

    model_config = ConfigDict(extra="forbid")


class MarkdownBlock(StrictPublicationModel):
    """A section of Markdown the author wrote, rendered without raw HTML."""

    type: Literal["markdown"]
    markdown: Annotated[
        str, StringConstraints(min_length=1, max_length=MAXIMUM_MARKDOWN_LENGTH)
    ]


class OutputBlock(StrictPublicationModel):
    """One of the report's output cards, named by v3's key for it."""

    type: Literal["output"]
    output: OutputKey


ContentBlock = Annotated[MarkdownBlock | OutputBlock, Field(discriminator="type")]
Content = Annotated[list[ContentBlock], Field(max_length=MAXIMUM_CONTENT_BLOCKS)]


def _duplicates(values: list[str]) -> list[str]:
    """Return the values that appear more than once, in first-seen order."""
    seen: set[str] = set()
    repeated: list[str] = []
    for value in values:
        if value in seen and value not in repeated:
            repeated.append(value)
        seen.add(value)
    return repeated


def require_distinct(
    *,
    author_ids: list[str] | None,
    tags: list[str] | None,
    content: list[MarkdownBlock | OutputBlock] | None,
) -> None:
    """Raise ValueError when an author, a tag or an output card repeats."""
    output_keys = [
        block.output for block in content or [] if isinstance(block, OutputBlock)
    ]
    for label, values in (
        ("author_ids", author_ids or []),
        ("tags", tags or []),
        ("output cards", output_keys),
    ):
        repeated = _duplicates(values)
        if repeated:
            msg = f"{label} may name each at most once; repeated: {repeated}"
            raise ValueError(msg)


class PublicationFields(StrictPublicationModel):
    """What a published report shows beside its run."""

    summary: PublishedSummary
    author_ids: AuthorIds
    tags: Tags = Field(default_factory=list)
    content: Content = Field(default_factory=list)
    show_past_versions: StrictBool = False

    @model_validator(mode="after")
    def _distinct(self) -> PublicationFields:
        require_distinct(
            author_ids=self.author_ids, tags=self.tags, content=self.content
        )
        return self


class PublicationCreateInput(PublicationFields):
    """A publication of a saved report: its fields and the run it shows.

    ``run_id`` is one of the report's runs: a report run of an economy or
    household report, or a budget-window run of a budget window.
    """

    run_id: ResourceId


class PublicationUpdateInput(StrictPublicationModel):
    """The fields of a published report an edit sends; the others stay.

    None of them may be sent as null.
    """

    summary: PublishedSummary | None = None
    author_ids: AuthorIds | None = None
    tags: Tags | None = None
    content: Content | None = None
    show_past_versions: StrictBool | None = None

    @model_validator(mode="after")
    def _checked(self) -> PublicationUpdateInput:
        cleared = sorted(
            name for name in self.model_fields_set if getattr(self, name) is None
        )
        if cleared:
            msg = f"{', '.join(cleared)} cannot be null"
            raise ValueError(msg)
        require_distinct(
            author_ids=self.author_ids, tags=self.tags, content=self.content
        )
        return self


class PublicationVersionInput(StrictPublicationModel):
    """The run a published report moves to, as its new version."""

    run_id: ResourceId


@dataclass(frozen=True)
class PublishedRun:
    """The run a version shows: a report run or a budget-window run, never both."""

    report_run_id: UUID | None = None
    budget_window_run_id: UUID | None = None


@dataclass(frozen=True)
class PublicationVersionRead:
    """One run a published report has shown, with the versions it ran on.

    ``run_id`` is a report run's or a budget-window run's ID; a budget-window
    run recorded before its versions were has none. ``published_at`` is when
    the page moved to the run.
    """

    id: UUID
    run_id: UUID
    country_package_version: str | None
    policyengine_version: str | None
    published_at: datetime


@dataclass(frozen=True)
class PublicationRead:
    """A published report as its owner reads it, with every version, newest first.

    ``published_at`` is when it was first published, and ``updated_at`` when
    any of it last changed.
    """

    user_report_id: UUID
    country_id: str
    summary: str
    author_ids: list[str]
    tags: list[str]
    content: list[MarkdownBlock | OutputBlock]
    show_past_versions: bool
    versions: tuple[PublicationVersionRead, ...]
    published_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ShownVersions:
    """The version a reader reads, and the versions a reader may open, newest first."""

    version: PublicationVersionRead
    readable: tuple[PublicationVersionRead, ...]


@dataclass(frozen=True)
class PublishedSavedReportRead:
    """The saved report's presentation a published report shows.

    The same as a shared report's, without its owner, its owner's notes or
    its owner's saved-reform IDs; the reform it was compared with is named.
    """

    source_note: str | None
    provisions: list[StoredJSONObject] | None
    validation: StoredJSONObject | None
    budget_window_years: int | None
    baseline_reform: SharedBaselineReformRead | None


@dataclass(frozen=True)
class PublishedReportRead:
    """A published report as anyone reads it.

    ``id`` is the saved report's ID, the page's link, and ``title`` the
    saved report's name. ``version`` is the version read, and ``report``
    the report with that version's run, labelled with the title.
    ``versions`` lists the versions a reader may open, newest first: every
    version while the author shows past versions, else only the newest.
    """

    id: UUID
    country_id: str
    title: str | None
    summary: str
    author_ids: list[str]
    tags: list[str]
    content: list[MarkdownBlock | OutputBlock]
    show_past_versions: bool
    saved_report: PublishedSavedReportRead
    version: PublicationVersionRead
    versions: tuple[PublicationVersionRead, ...]
    published_at: datetime
    updated_at: datetime
    report: StoredReportRead


class PublishedReportReader(Protocol):
    """Read a report with one of its runs, as ``GET /v2/reports/{id}`` does."""

    def get_report(
        self,
        *,
        country_id: str,
        report_id: UUID,
        run_id: UUID | None = None,
        requester: AccountPrincipal | None = None,
    ) -> StoredReportRead:
        """Return the country's report with its run ``run_id``."""
        ...
