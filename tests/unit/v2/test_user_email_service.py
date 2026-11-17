"""Tests for the invitation and type-change emails the Public API sends.

The service fills Postmark's templates and records a WARNING, naming no
email address, whenever an email isn't sent. A stand-in sender plays
Postmark and a stand-in reader plays Auth0; the Postmark client itself is
tested in ``tests/unit/libs/test_postmark_email.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import UserType
from policyengine_api.libs.auth0_management import Auth0UserProfilesUnavailableError
from policyengine_api.libs.postmark_email import EmailSendError
from policyengine_api.services.v2.user_emails import services as email_services
from policyengine_api.services.v2.user_emails.services import V2UserEmailService
from policyengine_api.services.v2.user_emails.types import (
    InvitationEmail,
    SignInIdentity,
    UserTypeChangeEmail,
)
from tests.unit.v2.user_email_support import (
    APP_URL,
    RecordingEmailSender,
    StandInProfileReader,
    auth0_profile,
    profile_source,
    recorded_logs,
    warnings_named,
)

ISSUER = "https://auth.example.test/"
OTHER_ISSUER = "https://other.example.test/"
USER_ID = UUID("00000000-0000-0000-0000-0000000000a1")
INVITATION_ID = UUID("00000000-0000-0000-0000-0000000000b1")
TOKEN = "x" * 43
INVITATION = InvitationEmail(
    invitation_id=INVITATION_ID,
    email="Ada@Example.org",
    user_type=UserType.AUTHOR,
    expires_at=datetime(2026, 11, 19, 14, 5, 59, tzinfo=UTC),
    token=TOKEN,
)
PROMOTION = UserTypeChangeEmail(
    user_id=USER_ID,
    previous_user_type=UserType.STANDARD,
    user_type=UserType.ADMIN,
    identities=(
        SignInIdentity(issuer=OTHER_ISSUER, subject="other|ada"),
        SignInIdentity(issuer=ISSUER, subject="auth0|ada-new"),
        SignInIdentity(issuer=ISSUER, subject="google-oauth2|ada"),
    ),
)


def _service(
    sender: RecordingEmailSender | None,
    reader: StandInProfileReader | None = None,
) -> V2UserEmailService:
    return V2UserEmailService(
        email_sender_factory=lambda: sender,
        user_profile_source_factory=(
            (lambda: None)
            if reader is None
            else (lambda: profile_source(ISSUER, reader))
        ),
    )


def test_an_invitation_email_links_to_the_accept_page_with_its_token() -> None:
    sender = RecordingEmailSender()

    failure = _service(sender).send_invitation(INVITATION)

    assert failure is None
    assert sender.sent == [
        {
            "to": "Ada@Example.org",
            "template_alias": "user-invitation",
            "template_model": {
                "user_type": "author",
                "accept_url": f"{APP_URL}/invitations/accept#token={TOKEN}",
                "expires_at": "19 November 2026, 14:05 UTC",
                "app_url": APP_URL,
            },
        }
    ]
    assert TOKEN not in repr(INVITATION)


@pytest.mark.parametrize(
    ("sender", "failure"),
    [
        (None, "not_configured"),
        (RecordingEmailSender(EmailSendError("postmark_406")), "postmark_406"),
        (RecordingEmailSender(RuntimeError("Ada@Example.org")), "unexpected_error"),
    ],
)
def test_an_unsent_invitation_names_its_failure_and_records_a_warning(
    sender: RecordingEmailSender | None, failure: str
) -> None:
    with recorded_logs(email_services.logger) as records:
        named_failure = _service(sender).send_invitation(INVITATION)

    assert named_failure == failure
    assert warnings_named(records, "user_invitation_email_not_sent") == [
        {"invitation_id": str(INVITATION_ID), "cause": failure}
    ]
    assert all("Ada@Example.org" not in record.getMessage() for record in records)


def test_an_unusable_sender_setting_counts_as_not_configured() -> None:
    def refuse() -> RecordingEmailSender:
        msg = "POSTMARK_SENDER_ADDRESS must be an email address"
        raise ValueError(msg)

    service = V2UserEmailService(
        email_sender_factory=refuse, user_profile_source_factory=lambda: None
    )

    with recorded_logs(email_services.logger) as records:
        assert service.send_invitation(INVITATION) == "not_configured"

    assert warnings_named(records, "user_invitation_email_not_sent") == [
        {"invitation_id": str(INVITATION_ID), "cause": "invalid_settings"}
    ]


def test_a_type_change_email_goes_to_the_first_verified_auth0_email() -> None:
    sender = RecordingEmailSender()
    reader = StandInProfileReader(
        [
            auth0_profile("auth0|ada-new", "new@example.org", verified=False),
            auth0_profile("google-oauth2|ada", "ada@example.org"),
        ]
    )

    failure = _service(sender, reader).send_type_change(PROMOTION)

    assert failure is None
    # Only identities from the users' issuer are Auth0 users, read together.
    assert reader.profile_reads == [("auth0|ada-new", "google-oauth2|ada")]
    assert sender.sent == [
        {
            "to": "ada@example.org",
            "template_alias": "user-type-changed",
            "template_model": {
                "previous_user_type": "standard",
                "user_type": "admin",
                "promoted": True,
                "app_url": APP_URL,
            },
        }
    ]


def test_a_demotion_email_says_it_is_not_a_promotion() -> None:
    sender = RecordingEmailSender()
    demotion = UserTypeChangeEmail(
        user_id=USER_ID,
        previous_user_type=UserType.ADMIN,
        user_type=UserType.AUTHOR,
        identities=(),
    )

    failure = _service(sender).send_type_change(
        demotion, verified_email="ada@example.org"
    )

    assert failure is None
    assert sender.sent[0]["template_model"] == {
        "previous_user_type": "admin",
        "user_type": "author",
        "promoted": False,
        "app_url": APP_URL,
    }


def test_a_known_verified_email_needs_no_auth0_read() -> None:
    sender = RecordingEmailSender()
    reader = StandInProfileReader()

    _service(sender, reader).send_type_change(
        PROMOTION, verified_email="ada@example.org"
    )

    assert reader.profile_reads == []
    assert sender.sent[0]["to"] == "ada@example.org"


@pytest.mark.parametrize(
    ("sender", "reader", "failure"),
    [
        (None, StandInProfileReader(), "not_configured"),
        (RecordingEmailSender(), None, "no_user_profiles"),
        (
            RecordingEmailSender(),
            StandInProfileReader(
                failure=Auth0UserProfilesUnavailableError("timeout", cause="timeout")
            ),
            "profiles_unavailable",
        ),
        (
            RecordingEmailSender(),
            StandInProfileReader(
                [auth0_profile("google-oauth2|ada", "ada@example.org", verified=False)]
            ),
            "no_verified_email",
        ),
        (RecordingEmailSender(), StandInProfileReader(), "no_verified_email"),
        (
            RecordingEmailSender(EmailSendError("timeout")),
            StandInProfileReader(
                [auth0_profile("google-oauth2|ada", "ada@example.org")]
            ),
            "timeout",
        ),
    ],
)
def test_an_unsent_type_change_email_records_a_warning_with_the_user_id_only(
    sender: RecordingEmailSender | None,
    reader: StandInProfileReader | None,
    failure: str,
) -> None:
    with recorded_logs(email_services.logger) as records:
        named_failure = _service(sender, reader).send_type_change(PROMOTION)

    assert named_failure == failure
    assert warnings_named(records, "user_type_change_email_not_sent") == [
        {"user_id": str(USER_ID), "cause": failure}
    ]
    if sender is not None:
        assert sender.sent == []


def test_nothing_is_read_from_auth0_when_no_email_can_be_sent() -> None:
    reader = StandInProfileReader(
        [auth0_profile("google-oauth2|ada", "ada@example.org")]
    )

    assert _service(None, reader).send_type_change(PROMOTION) == "not_configured"

    assert reader.profile_reads == []


def test_a_user_with_no_identity_from_the_users_issuer_reads_nothing() -> None:
    reader = StandInProfileReader()
    change = UserTypeChangeEmail(
        user_id=USER_ID,
        previous_user_type=UserType.STANDARD,
        user_type=UserType.AUTHOR,
        identities=(SignInIdentity(issuer=OTHER_ISSUER, subject="other|ada"),),
    )

    failure = _service(RecordingEmailSender(), reader).send_type_change(change)

    assert failure == "no_verified_email"
    assert reader.profile_reads == []
