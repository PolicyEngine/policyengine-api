"""Admins' email invitations to become an author or admin, and their acceptance.

An admin invites an email address; the invitation's token is sent only in
its email, after the invitation commits, and only the token's SHA-256 hash is
stored. Inviting an address again revokes its open invitation, and resending
one gives it a new token and expiry, so an earlier link stops working. A send
that fails leaves the invitation open with the failure recorded.

A signed-in user accepts with the token. Their email is first read from
Auth0 by their Auth0 user ID, and never stored. Then, in one transaction
under the user-type change lock, the token's invitation must be open and
unexpired (410), its inviting admin still an admin (409), the user's Auth0
email verified (409) and equal to the invited address ignoring case (403).
The user then gets the invited type, unless they already have it or a higher
one: an invitation never lowers a type. A change is recorded with the
inviting admin named, and the user is emailed about it after the commit.

Every invitation write takes the user-type change lock, which type changes
and account deletions take too, and checks the caller against the admins
read after it.
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserType, UserTypeChangeSource
from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.libs.rate_limit_wait_budget import RateLimitWaitBudget
from policyengine_api.services.v2.identity.services import (
    find_principal_user_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.user_emails.types import (
    InvitationEmail,
    SignInIdentity,
    UserTypeChangeEmail,
)
from policyengine_api.services.v2.user_invitations.database_connectors.creates import (
    create_user_invitation,
)
from policyengine_api.services.v2.user_invitations.database_connectors.reads import (
    read_invitation,
    read_invitation_by_token_hash,
    read_open_invitations,
    read_open_invitations_to,
)
from policyengine_api.services.v2.user_invitations.database_connectors.updates import (
    accept_invitation,
    record_invitation_send,
    renew_invitation,
    revoke_invitation,
)
from policyengine_api.services.v2.user_invitations.transformations import (
    admin_invitation_read,
    invitation_token_hash,
)
from policyengine_api.services.v2.user_invitations.types import (
    INVITATION_LIFETIME,
    INVITATION_TOKEN_BYTES,
    AdminInvitationPage,
    AdminInvitationRead,
    InvitationAcceptance,
    NewInvitation,
)
from policyengine_api.services.v2.user_invitations.validators import (
    InvitationEmailUnavailableError,
    InvitationNotFoundError,
    grants_new_type,
    require_acceptable_invitation,
    require_invitation_user_type,
    require_invited_email,
    require_inviter_admin,
    require_open_invitation,
    require_verified_email,
)
from policyengine_api.services.v2.user_types.database_connectors.creates import (
    create_user_type_change,
)
from policyengine_api.services.v2.user_types.database_connectors.reads import (
    acquire_user_type_change_lock,
    read_admin_user_ids,
    read_identities_newest_first,
    read_signed_in_user,
)
from policyengine_api.services.v2.user_types.database_connectors.updates import (
    update_user_type,
)
from policyengine_api.services.v2.user_types.transformations import caller_user_type
from policyengine_api.services.v2.user_types.types import UserTypeChangeOrigin
from policyengine_api.services.v2.user_types.validators import (
    require_minimum_user_type,
    require_signed_in_user,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserInvitation
    from policyengine_api.libs.auth0_management import Auth0UserProfile
    from policyengine_api.services.v2.identity.types import (
        AccountPrincipal,
        UserPrincipal,
    )
    from policyengine_api.services.v2.user_emails.services import V2UserEmailService
    from policyengine_api.services.v2.user_invitations.database_session import (
        UserInvitationDatabaseSession,
    )
    from policyengine_api.services.v2.user_invitations.types import (
        AdminInvitationSearch,
    )
    from policyengine_api.services.v2.user_types.types import UserProfileSource

logger = logging.getLogger(__name__)

INVITEE_EMAIL_UNAVAILABLE_EVENT = "invitee_email_unavailable"
INVITEE_EMAIL_UNAVAILABLE_MESSAGE = (
    "Your email address can't be checked right now; try again shortly"
)


def _new_token() -> str:
    """Return a new invitation token: 32 random bytes, URL-safe base64."""
    return secrets.token_urlsafe(INVITATION_TOKEN_BYTES)


def _lock_and_require_admin(session: Session, principal: AccountPrincipal) -> UUID:
    """Take the user-type change lock; return the caller's ID if an admin."""
    from policyengine_api.services.v2.user_types.services import (
        lock_and_require_admin_in_session,
    )

    return lock_and_require_admin_in_session(session, principal)


def _invitation_email(invitation: UserInvitation, token: str) -> InvitationEmail:
    return InvitationEmail(
        invitation_id=invitation.id,
        email=invitation.email,
        user_type=UserType(invitation.user_type),
        expires_at=invitation.expires_at,
        token=token,
    )


class V2UserInvitationService:
    """Sequence invitations and their acceptance through explicit sessions."""

    def __init__(
        self,
        database_session: UserInvitationDatabaseSession,
        *,
        user_email_service: V2UserEmailService,
        user_profile_source_factory: Callable[[], UserProfileSource | None],
        clock: Callable[[], datetime] = utc_now,
        token_factory: Callable[[], str] = _new_token,
    ) -> None:
        """Open every session through ``database_session``.

        ``user_email_service`` sends the invitation and type-change emails.
        ``user_profile_source_factory`` gives the users' Auth0 tenant, from
        which an invitee's verified email is read; with none, no invitation
        can be accepted. ``clock`` and ``token_factory`` are replaced in tests.
        """
        self._database_session = database_session
        self._emails = user_email_service
        self._user_profile_source_factory = user_profile_source_factory
        self._clock = clock
        self._token_factory = token_factory

    def create_invitation(
        self, *, principal: AccountPrincipal, email: str, user_type: UserType
    ) -> AdminInvitationRead:
        """Invite ``email`` to become ``user_type``, then email the link.

        The address's open invitation, if any, is revoked first. The
        returned invitation says whether the email was sent.
        """
        require_invitation_user_type(user_type)
        token = self._token_factory()
        now = self._clock()
        with self._database_session.transaction() as session:
            caller_user_id = _lock_and_require_admin(session, principal)
            for earlier in read_open_invitations_to(session, email):
                revoke_invitation(session, earlier, revoked_at=now)
            invitation = create_user_invitation(
                session,
                NewInvitation(
                    email=email,
                    user_type=user_type,
                    token_hash=invitation_token_hash(token),
                    invited_by_user_id=caller_user_id,
                    created_at=now,
                    expires_at=now + INVITATION_LIFETIME,
                ),
            )
            sending = _invitation_email(invitation, token)
        return self._send_invitation(sending)

    def list_invitations(
        self, *, principal: AccountPrincipal, search: AdminInvitationSearch
    ) -> AdminInvitationPage:
        """Return one page of open invitations, newest first, expired ones too."""
        now = self._clock()
        with self._database_session.read() as session:
            require_minimum_user_type(
                caller_user_type(
                    principal, find_principal_user_in_session(session, principal)
                ),
                UserType.ADMIN,
            )
            invitations = read_open_invitations(
                session, offset=search.offset, limit=search.limit + 1
            )
            items = tuple(
                admin_invitation_read(invitation, now=now)
                for invitation in invitations[: search.limit]
            )
        return AdminInvitationPage(
            items=items,
            offset=search.offset,
            limit=search.limit,
            has_more=len(invitations) > search.limit,
        )

    def resend_invitation(
        self, *, principal: AccountPrincipal, invitation_id: UUID
    ) -> AdminInvitationRead:
        """Give an open invitation a new link and expiry, and email it again.

        The caller becomes its inviting admin. Raise InvitationNotFoundError
        unless an open invitation has this ID.
        """
        token = self._token_factory()
        now = self._clock()
        with self._database_session.transaction() as session:
            caller_user_id = _lock_and_require_admin(session, principal)
            invitation = renew_invitation(
                session,
                require_open_invitation(
                    read_invitation(session, invitation_id, for_update=True)
                ),
                token_hash=invitation_token_hash(token),
                expires_at=now + INVITATION_LIFETIME,
                invited_by_user_id=caller_user_id,
            )
            sending = _invitation_email(invitation, token)
        return self._send_invitation(sending)

    def revoke_invitation(
        self, *, principal: AccountPrincipal, invitation_id: UUID
    ) -> None:
        """Revoke an open invitation, so its link stops working.

        Raise InvitationNotFoundError unless an open invitation has this ID.
        """
        now = self._clock()
        with self._database_session.transaction() as session:
            _lock_and_require_admin(session, principal)
            revoke_invitation(
                session,
                require_open_invitation(
                    read_invitation(session, invitation_id, for_update=True)
                ),
                revoked_at=now,
            )

    def _send_invitation(self, sending: InvitationEmail) -> AdminInvitationRead:
        """Email a committed invitation, then record how the send went.

        The record is skipped when the invitation's token changed meanwhile,
        since a later resend then owns it.
        """
        failure = self._emails.send_invitation(sending)
        now = self._clock()
        with self._database_session.transaction() as session:
            invitation = read_invitation(
                session, sending.invitation_id, for_update=True
            )
            if invitation is None:
                msg = "No pending invitation has this ID"
                raise InvitationNotFoundError(msg)
            if invitation.token_hash == invitation_token_hash(sending.token):
                record_invitation_send(
                    session,
                    invitation,
                    sent_at=now if failure is None else None,
                    send_error=failure,
                )
            return admin_invitation_read(invitation, now=now)

    def _invitee_profile(self, principal: UserPrincipal) -> Auth0UserProfile | None:
        """Read the signed-in invitee's Auth0 profile by their Auth0 user ID.

        Return None when the identity isn't from the users' Auth0 tenant or
        Auth0 doesn't know it. Raise InvitationEmailUnavailableError when
        there are no profile settings or Auth0 can't answer.
        """
        try:
            source = self._user_profile_source_factory()
        except Exception as error:
            self._record_unavailable("invalid_settings")
            raise InvitationEmailUnavailableError(
                INVITEE_EMAIL_UNAVAILABLE_MESSAGE
            ) from error
        if source is None:
            self._record_unavailable("no_user_profiles")
            raise InvitationEmailUnavailableError(INVITEE_EMAIL_UNAVAILABLE_MESSAGE)
        if principal.issuer != source.issuer:
            return None
        try:
            profiles = source.reader.read_user_profiles(
                (principal.subject,), wait_budget=RateLimitWaitBudget()
            )
        except Exception as error:
            cause = getattr(error, "cause", None)
            self._record_unavailable(cause if isinstance(cause, str) else "unknown")
            raise InvitationEmailUnavailableError(
                INVITEE_EMAIL_UNAVAILABLE_MESSAGE
            ) from error
        return profiles.get(principal.subject)

    @staticmethod
    def _record_unavailable(cause: str) -> None:
        """Record why an invitee's email couldn't be read, by cause only."""
        logger.warning(
            INVITEE_EMAIL_UNAVAILABLE_EVENT,
            extra={"policyengine_attributes": {"cause": cause[:40]}},
        )

    def accept_invitation(
        self, *, principal: UserPrincipal, token: str, country_id: str
    ) -> InvitationAcceptance:
        """Accept an invitation for the signed-in user, giving its type.

        A user with no account yet gets one, with ``country_id`` as its
        primary country, as on any first signed-in request. Raise, in this
        order: InvitationEmailUnavailableError (Auth0 can't answer), an
        InvitationUnavailableError for a token that is unknown, revoked,
        accepted or expired, InviterNotAdminError,
        InvitationEmailNotVerifiedError, then InvitationEmailMismatchError.
        Nothing changes when any is raised.
        """
        profile = self._invitee_profile(principal)
        token_hash = invitation_token_hash(token)
        now = self._clock()
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            acquire_user_type_change_lock(session)
            invitation = require_acceptable_invitation(
                read_invitation_by_token_hash(session, token_hash), now=now
            )
            require_inviter_admin(
                invitation.invited_by_user_id, read_admin_user_ids(session)
            )
            verified_email = require_verified_email(profile)
            require_invited_email(invitation.email, verified_email)
            user = require_signed_in_user(
                read_signed_in_user(session, owner.user_id, for_update=True)
            )
            previous_user_type = UserType(user.user_type)
            invited_user_type = UserType(invitation.user_type)
            type_changed = grants_new_type(previous_user_type, invited_user_type)
            if type_changed:
                update_user_type(session, user, user_type=invited_user_type)
                create_user_type_change(
                    session,
                    user_id=user.id,
                    previous_user_type=previous_user_type,
                    new_user_type=invited_user_type,
                    origin=UserTypeChangeOrigin(
                        changed_by_user_id=invitation.invited_by_user_id,
                        source=UserTypeChangeSource.INVITATION,
                    ),
                )
            user_id = user.id
            accept_invitation(
                session, invitation, accepted_at=now, accepted_by_user_id=user_id
            )
            identities = tuple(
                SignInIdentity(issuer=identity.issuer, subject=identity.subject)
                for identity in read_identities_newest_first(session, [user_id])
            )
            acceptance = InvitationAcceptance(
                user_type=UserType(user.user_type),
                previous_user_type=previous_user_type,
                type_changed=type_changed,
            )
        if type_changed:
            self._emails.send_type_change(
                UserTypeChangeEmail(
                    user_id=user_id,
                    previous_user_type=previous_user_type,
                    user_type=invited_user_type,
                    identities=identities,
                ),
                verified_email=verified_email,
            )
        return acceptance
