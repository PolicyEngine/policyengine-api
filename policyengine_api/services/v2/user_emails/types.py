"""Framework-independent data for the invitation and type-change emails."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from policyengine_api.data.v2.models import UserType

# The aliases of the Postmark templates each email fills in.
USER_INVITATION_TEMPLATE_ALIAS = "user-invitation"
USER_TYPE_CHANGED_TEMPLATE_ALIAS = "user-type-changed"


class TemplateEmailSender(Protocol):
    """Sends template emails: Postmark, or a stand-in in tests."""

    @property
    def app_url(self) -> str:
        """Return the app's address that emails link to, without a trailing slash."""
        ...

    def send_template(
        self,
        *,
        to: str,
        template_alias: str,
        template_model: Mapping[str, object],
    ) -> None:
        """Send one template email; raise when it isn't accepted."""
        ...


@dataclass(frozen=True)
class SignInIdentity:
    """One of a user's sign-in identities: its token issuer and subject."""

    issuer: str
    subject: str


@dataclass(frozen=True)
class UserTypeChangeEmail:
    """A committed change of a user's type, to email the user about."""

    user_id: UUID
    previous_user_type: UserType
    user_type: UserType
    # The user's sign-in identities, most recently seen first; the email goes
    # to the first verified Auth0 email among those from the users' issuer.
    identities: tuple[SignInIdentity, ...]


@dataclass(frozen=True)
class InvitationEmail:
    """A committed invitation, to email to its address with its token."""

    invitation_id: UUID
    email: str
    user_type: UserType
    expires_at: datetime
    # Sent only in the email: kept out of repr, and never logged or stored.
    token: str = field(repr=False)
