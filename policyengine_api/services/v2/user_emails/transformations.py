"""Pure conversions that fill the invitation and type-change email templates."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING
from urllib.parse import quote

from policyengine_api.data.v2.models import UserType

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime

    from policyengine_api.libs.auth0_management import Auth0UserProfile
    from policyengine_api.services.v2.user_emails.types import (
        InvitationEmail,
        SignInIdentity,
        UserTypeChangeEmail,
    )

# The app's page that accepts an invitation; the token travels in the URL
# fragment, which browsers never send to a server.
INVITATION_ACCEPT_PATH = "/invitations/accept"
USER_TYPE_ORDER = tuple(UserType)


def invitation_accept_url(app_url: str, token: str) -> str:
    """Return the link to the app's accept page, carrying ``token``."""
    return f"{app_url}{INVITATION_ACCEPT_PATH}#token={quote(token, safe='-_')}"


def expiry_text(moment: datetime) -> str:
    """Write a time as people read it in an email, in UTC, to the minute."""
    utc = moment.astimezone(UTC)
    return f"{utc.day} {utc:%B %Y, %H:%M} UTC"


def invitation_template_model(
    invitation: InvitationEmail, app_url: str
) -> dict[str, object]:
    """Return the data the ``user-invitation`` template fills in."""
    return {
        "user_type": invitation.user_type.value,
        "accept_url": invitation_accept_url(app_url, invitation.token),
        "expires_at": expiry_text(invitation.expires_at),
        "app_url": app_url,
    }


def type_change_template_model(
    change: UserTypeChangeEmail, app_url: str
) -> dict[str, object]:
    """Return the data the ``user-type-changed`` template fills in.

    ``promoted`` is true when the new type has more permissions than the
    previous one.
    """
    return {
        "previous_user_type": change.previous_user_type.value,
        "user_type": change.user_type.value,
        "promoted": USER_TYPE_ORDER.index(change.user_type)
        > USER_TYPE_ORDER.index(change.previous_user_type),
        "app_url": app_url,
    }


def subjects_from_issuer(
    identities: Iterable[SignInIdentity], issuer: str
) -> tuple[str, ...]:
    """Return the subjects of the identities from ``issuer``, in order, once each."""
    return tuple(
        dict.fromkeys(
            identity.subject for identity in identities if identity.issuer == issuer
        )
    )


def first_verified_email(
    subjects: Iterable[str], profiles: Mapping[str, Auth0UserProfile]
) -> str | None:
    """Return the first verified Auth0 email of these subjects, in their order."""
    for subject in subjects:
        profile = profiles.get(subject)
        if profile is not None and profile.email_verified and profile.email:
            return profile.email
    return None
