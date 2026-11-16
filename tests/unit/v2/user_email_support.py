"""Stand-ins for Postmark and Auth0 in invitation and type-change email tests."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from policyengine_api.libs.auth0_management import Auth0UserProfile

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from policyengine_api.libs.rate_limit_wait_budget import RateLimitWaitBudget
    from policyengine_api.services.v2.user_types.types import UserProfileSource

APP_URL = "https://app.example.test"


class RecordingEmailSender:
    """Record each template email; raise ``failure`` instead when it is set."""

    app_url = APP_URL

    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.sent: list[dict[str, Any]] = []

    def send_template(
        self,
        *,
        to: str,
        template_alias: str,
        template_model: Mapping[str, object],
    ) -> None:
        if self.failure is not None:
            raise self.failure
        self.sent.append(
            {
                "to": to,
                "template_alias": template_alias,
                "template_model": dict(template_model),
            }
        )


class StandInProfileReader:
    """Answer Auth0 profile reads from ``profiles``, or raise ``failure``."""

    def __init__(
        self,
        profiles: Iterable[Auth0UserProfile] = (),
        *,
        failure: Exception | None = None,
    ) -> None:
        self.profiles = {profile.user_id: profile for profile in profiles}
        self.failure = failure
        # Reads of several users (Auth0's search) and of one user by ID.
        self.profile_reads: list[tuple[str, ...]] = []
        self.single_reads: list[str] = []

    def read_user_profiles(
        self,
        user_ids: Iterable[str],
        *,
        wait_budget: RateLimitWaitBudget | None = None,
    ) -> dict[str, Auth0UserProfile]:
        del wait_budget
        requested = tuple(user_ids)
        self.profile_reads.append(requested)
        if self.failure is not None:
            raise self.failure
        return {
            user_id: self.profiles[user_id]
            for user_id in requested
            if user_id in self.profiles
        }

    def read_user_profile(
        self, user_id: str, *, wait_budget: RateLimitWaitBudget | None = None
    ) -> Auth0UserProfile | None:
        del wait_budget
        self.single_reads.append(user_id)
        if self.failure is not None:
            raise self.failure
        return self.profiles.get(user_id)

    def search_user_ids_by_email(self, *_args: object, **_kwargs: object) -> object:
        msg = "invitations and type-change emails never search by email"
        raise AssertionError(msg)


def auth0_profile(
    subject: str, email: str | None, *, verified: bool = True
) -> Auth0UserProfile:
    """Build the Auth0 profile of ``subject`` with ``email``."""
    return Auth0UserProfile(
        user_id=subject,
        email=email,
        email_verified=verified,
        given_name=None,
        family_name=None,
        name=None,
    )


def profile_source(issuer: str, reader: StandInProfileReader) -> UserProfileSource:
    """Return the users' Auth0 tenant as ``reader`` plays it."""
    from policyengine_api.services.v2.user_types.types import UserProfileSource

    return UserProfileSource(issuer=issuer, reader=reader)


def warnings_named(records: Iterable[Any], event: str) -> list[dict[str, Any]]:
    """Return the attributes of each WARNING record named ``event``."""
    return [
        record.policyengine_attributes
        for record in records
        if record.getMessage() == event and record.levelname == "WARNING"
    ]


@contextmanager
def recorded_logs(logger: logging.Logger) -> Iterator[list[logging.LogRecord]]:
    """Record ``logger``'s records, even after a test disabled it.

    Alembic's tests configure logging from a file, which disables loggers
    that already exist, so the logger is enabled here and records are taken
    from it directly.
    """
    records: list[logging.LogRecord] = []

    class RecordingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = RecordingHandler(level=logging.INFO)
    previous_disabled, previous_level = logger.disabled, logger.level
    logger.disabled = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.disabled = previous_disabled
        logger.setLevel(previous_level)
