"""Strict HTTP request models for v2 user-report associations."""

from policyengine_api.services.v2.user_reports.types import (
    UserReportCreateFields,
    UserReportUpdateInput,
)


class UserReportCreateRequest(UserReportCreateFields):
    """Association fields; the owner is taken from the request credential."""


class UserReportPatchRequest(UserReportUpdateInput):
    """Explicitly supplied mutable link or presentation fields."""
