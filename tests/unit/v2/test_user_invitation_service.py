"""Service tests for admins' email invitations and their acceptance.

An admin invites an email address to become an author or admin; the signed-in
invitee accepts with the token from the email once Auth0 reports their
verified email matching the address. Stand-ins play Postmark and Auth0.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlmodel import select

from policyengine_api.data.v2.models import (
    User,
    UserInvitation,
    UserType,
    UserTypeChange,
)
from policyengine_api.libs.auth0_management import Auth0UserProfilesUnavailableError
from policyengine_api.libs.postmark_email import EmailSendError
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_emails.services import V2UserEmailService
from policyengine_api.services.v2.user_invitations.database_session import (
    UserInvitationDatabaseSession,
)
from policyengine_api.services.v2.user_invitations.services import (
    V2UserInvitationService,
)
from policyengine_api.services.v2.user_invitations.types import (
    AdminInvitationSearch,
    InvitationAcceptance,
)
from policyengine_api.services.v2.user_invitations.validators import (
    InvitationAcceptedError,
    InvitationEmailMismatchError,
    InvitationEmailNotVerifiedError,
    InvitationEmailUnavailableError,
    InvitationExpiredError,
    InvitationNotFoundError,
    InvitationRevokedError,
    InvitationTokenNotFoundError,
    InviterNotAdminError,
)
from policyengine_api.services.v2.user_types.validators import (
    UserTypeBelowMinimumError,
)
from tests.unit.v2.user_email_support import (
    APP_URL,
    RecordingEmailSender,
    StandInProfileReader,
    auth0_profile,
    profile_source,
)
from tests.unit.v2.user_service_support import ALICE, BOB, ISSUER, V2Store, v2_store

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

NOW = datetime(2026, 11, 12, 14, 5, tzinfo=UTC)
CAROL = UserPrincipal(issuer=ISSUER, subject="google-oauth2|carol")
BOB_EMAIL = "bob@example.test"


def _never_build_the_auth0_deleter():
    msg = "these tests delete no account"
    raise AssertionError(msg)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Invitations:
    """A store, the invitation service on it, and the stand-ins it uses."""

    def __init__(self, store: V2Store) -> None:
        self.store = store
        self.sender = RecordingEmailSender()
        self.reader = StandInProfileReader(
            [auth0_profile(BOB.subject, BOB_EMAIL), auth0_profile(CAROL.subject, None)]
        )
        self.profiles_configured = True
        self.now = NOW
        self._token_number = 0

    def _token(self) -> str:
        self._token_number += 1
        return f"token-{self._token_number:02d}-" + "x" * 34

    def service(self) -> V2UserInvitationService:
        def source():
            if not self.profiles_configured:
                return None
            return profile_source(ISSUER, self.reader)

        return V2UserInvitationService(
            UserInvitationDatabaseSession(self.store.sessions),
            user_email_service=V2UserEmailService(
                email_sender_factory=lambda: self.sender,
                user_profile_source_factory=source,
            ),
            user_profile_source_factory=source,
            clock=lambda: self.now,
            token_factory=self._token,
        )

    def sign_in(self, principal: UserPrincipal, user_type: UserType) -> UUID:
        accounts = V2AccountService(
            AccountDatabaseSession(self.store.sessions),
            auth0_user_deleter_factory=_never_build_the_auth0_deleter,
        )
        user_id = accounts.get_account(principal=principal, country_id="us").id
        with self.store.sessions.begin() as session:
            user = session.get(User, user_id)
            assert user is not None
            user.user_type = user_type.value
        return user_id

    def stored_type(self, user_id: UUID) -> UserType:
        with self.store.sessions() as session:
            user = session.get(User, user_id)
            assert user is not None
            return UserType(user.user_type)

    def invitations(self) -> list[UserInvitation]:
        with self.store.sessions() as session:
            return list(session.exec(select(UserInvitation)).all())

    def changes(self) -> list[UserTypeChange]:
        with self.store.sessions() as session:
            return list(session.exec(select(UserTypeChange)).all())

    def sent_tokens(self) -> list[str]:
        return [
            email["template_model"]["accept_url"].split("#token=", 1)[1]
            for email in self.sender.sent
            if email["template_alias"] == "user-invitation"
        ]


@pytest.fixture
def invitations() -> Iterator[Invitations]:
    with v2_store() as store:
        yield Invitations(store)


def _invite(
    invitations: Invitations,
    email: str = BOB_EMAIL,
    user_type: UserType = UserType.AUTHOR,
):
    return invitations.service().create_invitation(
        principal=ALICE, email=email, user_type=user_type
    )


def _accept(invitations: Invitations, token: str, principal: UserPrincipal = BOB):
    return invitations.service().accept_invitation(
        principal=principal, token=token, country_id="uk"
    )


def test_an_admin_invites_an_address_and_only_the_tokens_hash_is_stored(
    invitations: Invitations,
) -> None:
    admin_id = invitations.sign_in(ALICE, UserType.ADMIN)

    read = _invite(invitations, email="Bob@Example.test", user_type=UserType.ADMIN)

    (stored,) = invitations.invitations()
    (token,) = invitations.sent_tokens()
    assert stored.token_hash == _hash(token)
    assert token not in repr(stored.model_dump())
    assert read.id == stored.id
    assert read.email == "Bob@Example.test"
    assert read.user_type is UserType.ADMIN
    assert read.invited_by_user_id == admin_id
    assert read.expires_at == NOW + timedelta(days=7)
    assert read.expired is False
    assert read.last_sent_at == NOW
    assert read.last_send_error is None
    assert invitations.sender.sent == [
        {
            "to": "Bob@Example.test",
            "template_alias": "user-invitation",
            "template_model": {
                "user_type": "admin",
                "accept_url": f"{APP_URL}/invitations/accept#token={token}",
                "expires_at": "19 November 2026, 14:05 UTC",
                "app_url": APP_URL,
            },
        }
    ]


@pytest.mark.parametrize("caller_type", [UserType.STANDARD, UserType.AUTHOR])
def test_only_admins_invite(invitations: Invitations, caller_type: UserType) -> None:
    invitations.sign_in(ALICE, caller_type)

    with pytest.raises(UserTypeBelowMinimumError):
        _invite(invitations)

    assert invitations.invitations() == []
    assert invitations.sender.sent == []


def test_inviting_an_address_again_revokes_its_open_invitation(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sign_in(BOB, UserType.STANDARD)
    first = _invite(invitations, email="BOB@example.test")
    invitations.now = NOW + timedelta(hours=1)

    second = _invite(invitations, user_type=UserType.ADMIN)

    stored = {invitation.id: invitation for invitation in invitations.invitations()}
    assert stored[first.id].revoked_at is not None
    assert stored[second.id].revoked_at is None
    first_token, _second_token = invitations.sent_tokens()
    with pytest.raises(InvitationRevokedError):
        _accept(invitations, first_token)


def test_a_failed_send_keeps_the_invitation_with_its_failure(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sender.failure = EmailSendError("postmark_406")

    read = _invite(invitations)

    assert read.last_sent_at is None
    assert read.last_send_error == "postmark_406"
    (stored,) = invitations.invitations()
    assert stored.last_send_error == "postmark_406"
    assert stored.revoked_at is None


def test_without_postmark_the_invitation_is_kept_as_not_sent(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sender = None  # type: ignore[assignment]  # no Postmark settings

    read = _invite(invitations)

    assert read.last_send_error == "not_configured"
    assert read.last_sent_at is None


def test_admins_list_open_invitations_newest_first_with_expired_ones(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    oldest = _invite(invitations, email="old@example.test")
    invitations.now = NOW + timedelta(days=1)
    revoked = _invite(invitations, email="revoked@example.test")
    invitations.service().revoke_invitation(principal=ALICE, invitation_id=revoked.id)
    invitations.now = NOW + timedelta(days=2)
    newest = _invite(invitations, email="new@example.test")
    invitations.now = NOW + timedelta(days=7, seconds=1)

    first_page = invitations.service().list_invitations(
        principal=ALICE, search=AdminInvitationSearch(offset=0, limit=1)
    )
    second_page = invitations.service().list_invitations(
        principal=ALICE, search=AdminInvitationSearch(offset=1, limit=1)
    )

    assert [item.id for item in first_page.items] == [newest.id]
    assert first_page.has_more is True
    assert first_page.items[0].expired is False
    assert [item.id for item in second_page.items] == [oldest.id]
    assert second_page.has_more is False
    assert second_page.items[0].expired is True


def test_accepted_invitations_are_not_listed(invitations: Invitations) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    _invite(invitations)
    (token,) = invitations.sent_tokens()
    _accept(invitations, token)

    page = invitations.service().list_invitations(
        principal=ALICE, search=AdminInvitationSearch()
    )

    assert page.items == ()


def test_only_admins_list_resend_or_revoke(invitations: Invitations) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sign_in(BOB, UserType.AUTHOR)
    invitation = _invite(invitations)
    service = invitations.service()

    with pytest.raises(UserTypeBelowMinimumError):
        service.list_invitations(principal=BOB, search=AdminInvitationSearch())
    with pytest.raises(UserTypeBelowMinimumError):
        service.resend_invitation(principal=BOB, invitation_id=invitation.id)
    with pytest.raises(UserTypeBelowMinimumError):
        service.revoke_invitation(principal=BOB, invitation_id=invitation.id)

    (stored,) = invitations.invitations()
    assert stored.revoked_at is None
    assert len(invitations.sender.sent) == 1


def test_resending_replaces_the_token_and_expiry_and_names_the_resender(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    carol_id = invitations.sign_in(CAROL, UserType.ADMIN)
    invitations.sign_in(BOB, UserType.STANDARD)
    invitations.sender.failure = EmailSendError("timeout")
    invitation = _invite(invitations)
    invitations.sender.failure = None
    invitations.now = NOW + timedelta(days=8)

    resent = invitations.service().resend_invitation(
        principal=CAROL, invitation_id=invitation.id
    )

    assert resent.id == invitation.id
    assert resent.invited_by_user_id == carol_id
    assert resent.expires_at == NOW + timedelta(days=15)
    assert resent.expired is False
    assert resent.last_sent_at == NOW + timedelta(days=8)
    assert resent.last_send_error is None
    (token,) = invitations.sent_tokens()
    (stored,) = invitations.invitations()
    assert stored.token_hash == _hash(token)
    assert _accept(invitations, token).type_changed is True


def test_a_resent_invitations_earlier_link_no_longer_works(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sign_in(BOB, UserType.STANDARD)
    invitation = _invite(invitations)
    invitations.service().resend_invitation(
        principal=ALICE, invitation_id=invitation.id
    )
    earlier_token, _later_token = invitations.sent_tokens()

    with pytest.raises(InvitationTokenNotFoundError):
        _accept(invitations, earlier_token)


def test_revoking_closes_the_invitation_and_its_link(invitations: Invitations) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sign_in(BOB, UserType.STANDARD)
    invitation = _invite(invitations)
    service = invitations.service()

    service.revoke_invitation(principal=ALICE, invitation_id=invitation.id)

    (stored,) = invitations.invitations()
    assert stored.revoked_at is not None
    (token,) = invitations.sent_tokens()
    with pytest.raises(InvitationRevokedError):
        _accept(invitations, token)
    with pytest.raises(InvitationNotFoundError):
        service.revoke_invitation(principal=ALICE, invitation_id=invitation.id)
    with pytest.raises(InvitationNotFoundError):
        service.resend_invitation(principal=ALICE, invitation_id=invitation.id)


def test_an_accepted_invitation_is_neither_resent_nor_revoked(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitation = _invite(invitations)
    (token,) = invitations.sent_tokens()
    _accept(invitations, token)
    service = invitations.service()

    with pytest.raises(InvitationNotFoundError):
        service.resend_invitation(principal=ALICE, invitation_id=invitation.id)
    with pytest.raises(InvitationNotFoundError):
        service.revoke_invitation(principal=ALICE, invitation_id=invitation.id)


def test_accepting_gives_the_invited_type_and_emails_the_user(
    invitations: Invitations,
) -> None:
    admin_id = invitations.sign_in(ALICE, UserType.ADMIN)
    bob_id = invitations.sign_in(BOB, UserType.STANDARD)
    invitation = _invite(invitations, email="BOB@EXAMPLE.TEST")
    (token,) = invitations.sent_tokens()
    invitations.now = NOW + timedelta(days=1)

    acceptance = _accept(invitations, token)

    assert acceptance == InvitationAcceptance(
        user_type=UserType.AUTHOR,
        previous_user_type=UserType.STANDARD,
        type_changed=True,
    )
    assert invitations.stored_type(bob_id) is UserType.AUTHOR
    (stored,) = invitations.invitations()
    assert stored.id == invitation.id
    assert stored.accepted_by_user_id == bob_id
    assert stored.accepted_at is not None
    (change,) = invitations.changes()
    assert change.user_id == bob_id
    assert change.changed_by_user_id == admin_id
    assert (change.previous_user_type, change.new_user_type, change.source) == (
        "standard",
        "author",
        "invitation",
    )
    # Auth0's verified email was read once by user ID, which Auth0 answers at
    # once, unlike its search, before the change; the type-change email goes
    # there after the commit.
    assert invitations.reader.single_reads == [BOB.subject]
    assert invitations.reader.profile_reads == []
    assert invitations.sender.sent[-1] == {
        "to": BOB_EMAIL,
        "template_alias": "user-type-changed",
        "template_model": {
            "previous_user_type": "standard",
            "user_type": "author",
            "promoted": True,
            "app_url": APP_URL,
        },
    }


def test_accepting_creates_a_new_users_account_first(invitations: Invitations) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    _invite(invitations, user_type=UserType.ADMIN)
    (token,) = invitations.sent_tokens()

    acceptance = _accept(invitations, token)

    assert acceptance.type_changed is True
    assert acceptance.user_type is UserType.ADMIN
    with invitations.store.sessions() as session:
        (bob,) = [
            user
            for user in session.exec(select(User)).all()
            if user.user_type == "admin" and user.primary_country == "uk"
        ]
        assert bob is not None


@pytest.mark.parametrize("stored_type", [UserType.AUTHOR, UserType.ADMIN])
def test_an_invitation_never_lowers_or_repeats_a_type(
    invitations: Invitations, stored_type: UserType
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    bob_id = invitations.sign_in(BOB, stored_type)
    _invite(invitations, user_type=UserType.AUTHOR)
    (token,) = invitations.sent_tokens()

    acceptance = _accept(invitations, token)

    assert acceptance == InvitationAcceptance(
        user_type=stored_type, previous_user_type=stored_type, type_changed=False
    )
    assert invitations.stored_type(bob_id) is stored_type
    (stored,) = invitations.invitations()
    assert stored.accepted_by_user_id == bob_id
    assert invitations.changes() == []
    assert [email["template_alias"] for email in invitations.sender.sent] == [
        "user-invitation"
    ]


def _assert_still_open(invitations: Invitations, bob_id: UUID) -> None:
    (stored,) = invitations.invitations()
    assert stored.accepted_at is None
    assert stored.revoked_at is None
    assert invitations.stored_type(bob_id) is UserType.STANDARD
    assert invitations.changes() == []


def test_auth0_is_read_before_the_token_is_checked(invitations: Invitations) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    bob_id = invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations)
    invitations.reader.failure = Auth0UserProfilesUnavailableError(
        "unavailable", cause="http_503"
    )

    with pytest.raises(InvitationEmailUnavailableError):
        _accept(invitations, "not-a-token")

    _assert_still_open(invitations, bob_id)


def test_without_auth0_profile_settings_no_invitation_is_accepted(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    bob_id = invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations)
    (token,) = invitations.sent_tokens()
    invitations.profiles_configured = False

    with pytest.raises(InvitationEmailUnavailableError):
        _accept(invitations, token)

    _assert_still_open(invitations, bob_id)


def test_an_unknown_token_is_not_found(invitations: Invitations) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    bob_id = invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations)

    with pytest.raises(InvitationTokenNotFoundError):
        _accept(invitations, "token-99-" + "x" * 34)

    _assert_still_open(invitations, bob_id)


def test_an_expired_invitation_is_refused(invitations: Invitations) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    bob_id = invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations)
    (token,) = invitations.sent_tokens()
    invitations.now = NOW + timedelta(days=7)

    with pytest.raises(InvitationExpiredError):
        _accept(invitations, token)

    _assert_still_open(invitations, bob_id)


def test_an_accepted_invitation_is_refused_the_second_time(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations)
    (token,) = invitations.sent_tokens()
    _accept(invitations, token)

    with pytest.raises(InvitationAcceptedError):
        _accept(invitations, token)

    assert len(invitations.changes()) == 1


def test_an_invitation_from_a_former_admin_is_refused(invitations: Invitations) -> None:
    alice_id = invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sign_in(CAROL, UserType.ADMIN)
    bob_id = invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations)
    (token,) = invitations.sent_tokens()
    with invitations.store.sessions.begin() as session:
        alice = session.get(User, alice_id)
        assert alice is not None
        alice.user_type = UserType.AUTHOR.value

    with pytest.raises(InviterNotAdminError):
        _accept(invitations, token)

    _assert_still_open(invitations, bob_id)


def test_an_unverified_email_is_refused_until_auth0_verifies_it(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    bob_id = invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations)
    (token,) = invitations.sent_tokens()
    invitations.reader.profiles[BOB.subject] = auth0_profile(
        BOB.subject, BOB_EMAIL, verified=False
    )

    with pytest.raises(InvitationEmailNotVerifiedError):
        _accept(invitations, token)

    _assert_still_open(invitations, bob_id)
    invitations.reader.profiles[BOB.subject] = auth0_profile(BOB.subject, BOB_EMAIL)
    assert _accept(invitations, token).type_changed is True


def test_a_user_auth0_doesnt_know_has_no_verified_email(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    bob_id = invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations)
    (token,) = invitations.sent_tokens()
    del invitations.reader.profiles[BOB.subject]

    with pytest.raises(InvitationEmailNotVerifiedError):
        _accept(invitations, token)

    _assert_still_open(invitations, bob_id)


def test_another_verified_email_is_refused_and_the_invitation_stays_open(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    bob_id = invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations, email="bobby@example.test")
    (token,) = invitations.sent_tokens()

    with pytest.raises(InvitationEmailMismatchError):
        _accept(invitations, token)

    _assert_still_open(invitations, bob_id)


def test_the_token_is_checked_before_the_inviter_and_the_email(
    invitations: Invitations,
) -> None:
    alice_id = invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sign_in(CAROL, UserType.ADMIN)
    invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations, email="bobby@example.test")
    (token,) = invitations.sent_tokens()
    invitations.reader.profiles[BOB.subject] = auth0_profile(
        BOB.subject, BOB_EMAIL, verified=False
    )
    with invitations.store.sessions.begin() as session:
        alice = session.get(User, alice_id)
        assert alice is not None
        alice.user_type = UserType.STANDARD.value
    invitations.now = NOW + timedelta(days=8)

    with pytest.raises(InvitationExpiredError):
        _accept(invitations, token)
    invitations.now = NOW
    with pytest.raises(InviterNotAdminError):
        _accept(invitations, token)
    with invitations.store.sessions.begin() as session:
        alice = session.get(User, alice_id)
        assert alice is not None
        alice.user_type = UserType.ADMIN.value
    with pytest.raises(InvitationEmailNotVerifiedError):
        _accept(invitations, token)
    invitations.reader.profiles[BOB.subject] = auth0_profile(BOB.subject, BOB_EMAIL)
    with pytest.raises(InvitationEmailMismatchError):
        _accept(invitations, token)


def test_deleting_an_account_deletes_the_invitations_it_accepted(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sign_in(BOB, UserType.STANDARD)
    _invite(invitations)
    (token,) = invitations.sent_tokens()
    _accept(invitations, token)
    open_invitation = _invite(invitations, email="carol@example.test")

    V2AccountService(
        AccountDatabaseSession(invitations.store.sessions),
        auth0_user_deleter_factory=lambda: None,
    ).delete_account(principal=BOB)

    # The accepted invitation held Bob's address; the open one is kept.
    assert [invitation.id for invitation in invitations.invitations()] == [
        open_invitation.id
    ]


class ResendingSender(RecordingEmailSender):
    """Fail the first email after a resend has replaced its invitation's token."""

    def __init__(self, invitations: Invitations) -> None:
        super().__init__()
        self.invitations = invitations

    def send_template(self, *, to, template_alias, template_model) -> None:
        super().send_template(
            to=to, template_alias=template_alias, template_model=template_model
        )
        if len(self.sent) == 1:
            (invitation,) = self.invitations.invitations()
            self.invitations.service().resend_invitation(
                principal=ALICE, invitation_id=invitation.id
            )
            cause = "timeout"
            raise EmailSendError(cause)


def test_a_send_isnt_recorded_over_a_resend_that_replaced_its_link(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sender = ResendingSender(invitations)

    created = _invite(invitations)

    # The resend's successful send stands; the earlier link's failure is
    # not recorded over it.
    assert created.last_send_error is None
    assert created.last_sent_at == NOW
    (stored,) = invitations.invitations()
    _earlier_token, later_token = invitations.sent_tokens()
    assert stored.token_hash == _hash(later_token)
    assert stored.last_send_error is None


class DeletingSender(RecordingEmailSender):
    """Delete the invitation while its email is sent."""

    def __init__(self, invitations: Invitations) -> None:
        super().__init__()
        self.invitations = invitations

    def send_template(self, *, to, template_alias, template_model) -> None:
        super().send_template(
            to=to, template_alias=template_alias, template_model=template_model
        )
        with self.invitations.store.sessions.begin() as session:
            for invitation in session.exec(select(UserInvitation)).all():
                session.delete(invitation)


def test_an_invitation_gone_before_its_send_is_recorded_is_not_found(
    invitations: Invitations,
) -> None:
    invitations.sign_in(ALICE, UserType.ADMIN)
    invitations.sender = DeletingSender(invitations)

    with pytest.raises(InvitationNotFoundError):
        _invite(invitations)
