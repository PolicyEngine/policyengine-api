"""Strict HTTP request models for v2 published reports."""

from policyengine_api.services.v2.published_reports.types import (
    PublicationCreateInput,
    PublicationUpdateInput,
    PublicationVersionInput,
)


class PublicationCreateRequest(PublicationCreateInput):
    """A publication's fields and the run it shows; the owner is the credential's."""


class PublicationPatchRequest(PublicationUpdateInput):
    """The published report's fields to change; the others stay."""


class PublicationVersionRequest(PublicationVersionInput):
    """The run the published report moves to, as its new version."""
