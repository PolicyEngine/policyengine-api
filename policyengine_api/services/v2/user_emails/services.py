"""Send the invitation and type-change emails through a template email sender.

An email goes out only after the change it reports has committed, and a
failure to send never undoes or fails that change: each unsent email is
recorded as a WARNING naming the invitation or the user by ID and the cause,
never an email address. A type-change email goes to the user's verified
email as Auth0 has it, read when the email is sent and never stored.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from policyengine_api.libs.rate_limit_wait_budget import RateLimitWaitBudget
from policyengine_api.services.v2.user_emails.transformations import (
    first_verified_email,
    invitation_template_model,
    subjects_from_issuer,
    type_change_template_model,
)
from policyengine_api.services.v2.user_emails.types import (
    USER_INVITATION_TEMPLATE_ALIAS,
    USER_TYPE_CHANGED_TEMPLATE_ALIAS,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from policyengine_api.services.v2.user_emails.types import (
        InvitationEmail,
        TemplateEmailSender,
        UserTypeChangeEmail,
    )
    from policyengine_api.services.v2.user_types.types import UserProfileSource

logger = logging.getLogger(__name__)

INVITATION_EMAIL_NOT_SENT_EVENT = "user_invitation_email_not_sent"
TYPE_CHANGE_EMAIL_NOT_SENT_EVENT = "user_type_change_email_not_sent"
# Failure causes besides an EmailSendError's own.
NOT_CONFIGURED = "not_configured"
INVALID_SETTINGS = "invalid_settings"
NO_USER_PROFILES = "no_user_profiles"
PROFILES_UNAVAILABLE = "profiles_unavailable"
NO_VERIFIED_EMAIL = "no_verified_email"
UNEXPECTED_ERROR = "unexpected_error"
# A sender's failure cause is a short identifier such as http_500 or
# postmark_406, so no email address can pass as one.
SAFE_CAUSE_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,39}")


def _send_failure_cause(error: Exception) -> str:
    """Return the cause a sender's error names, else ``unexpected_error``.

    Postmark's EmailSendError carries a ``cause``; any other failure is
    unexpected.
    """
    cause = getattr(error, "cause", None)
    if isinstance(cause, str) and SAFE_CAUSE_PATTERN.fullmatch(cause):
        return cause
    return UNEXPECTED_ERROR


def _record_unsent(event: str, attributes: Mapping[str, str]) -> None:
    logger.warning(event, extra={"policyengine_attributes": dict(attributes)})


class V2UserEmailService:
    """Fill and send the invitation and type-change emails."""

    def __init__(
        self,
        *,
        email_sender_factory: Callable[[], TemplateEmailSender | None],
        user_profile_source_factory: Callable[[], UserProfileSource | None],
    ) -> None:
        """Build the sender and the Auth0 profile source only when sending.

        Either factory returns None when it isn't configured; then no email,
        or no type-change email, is sent.
        """
        self._email_sender_factory = email_sender_factory
        self._user_profile_source_factory = user_profile_source_factory

    def _sender(self) -> tuple[TemplateEmailSender | None, str]:
        """Return the sender, or None and why there is none."""
        try:
            sender = self._email_sender_factory()
        except Exception:  # noqa: BLE001  # unusable settings send nothing
            return None, INVALID_SETTINGS
        return sender, NOT_CONFIGURED

    def _send(
        self,
        sender: TemplateEmailSender,
        *,
        to: str,
        template_alias: str,
        template_model: Mapping[str, object],
    ) -> str | None:
        """Send one email; return None, or the cause it wasn't sent."""
        try:
            sender.send_template(
                to=to, template_alias=template_alias, template_model=template_model
            )
        except Exception as error:  # noqa: BLE001  # a committed change must not fail on its email
            return _send_failure_cause(error)
        return None

    def send_invitation(self, invitation: InvitationEmail) -> str | None:
        """Email an invitation's link to its address.

        Return None when Postmark accepted it, else the cause it wasn't sent:
        ``not_configured``, or the sender's cause, such as ``timeout`` or
        ``postmark_406``.
        """
        sender, missing_cause = self._sender()
        if sender is None:
            _record_unsent(
                INVITATION_EMAIL_NOT_SENT_EVENT,
                {
                    "invitation_id": str(invitation.invitation_id),
                    "cause": missing_cause,
                },
            )
            return NOT_CONFIGURED
        cause = self._send(
            sender,
            to=invitation.email,
            template_alias=USER_INVITATION_TEMPLATE_ALIAS,
            template_model=invitation_template_model(invitation, sender.app_url),
        )
        if cause is not None:
            _record_unsent(
                INVITATION_EMAIL_NOT_SENT_EVENT,
                {"invitation_id": str(invitation.invitation_id), "cause": cause},
            )
        return cause

    def _verified_email(self, change: UserTypeChangeEmail) -> tuple[str | None, str]:
        """Read the user's first verified Auth0 email, or say why there is none."""
        try:
            source = self._user_profile_source_factory()
        except Exception:  # noqa: BLE001  # unusable settings read nothing
            return None, NO_USER_PROFILES
        if source is None:
            return None, NO_USER_PROFILES
        subjects = subjects_from_issuer(change.identities, source.issuer)
        if not subjects:
            return None, NO_VERIFIED_EMAIL
        try:
            profiles = source.reader.read_user_profiles(
                subjects, wait_budget=RateLimitWaitBudget()
            )
        except Exception:  # noqa: BLE001  # Auth0's failure leaves the change committed
            return None, PROFILES_UNAVAILABLE
        email = first_verified_email(subjects, profiles)
        return email, NO_VERIFIED_EMAIL

    def send_type_change(
        self, change: UserTypeChangeEmail, *, verified_email: str | None = None
    ) -> str | None:
        """Email a user about a committed change of their type.

        The email goes to ``verified_email`` when the caller already read it
        from Auth0, else to the first verified Auth0 email of the user's
        identities from the users' issuer, most recently seen first. Return
        None when Postmark accepted it, else the cause it wasn't sent:
        ``not_configured``, ``no_user_profiles``, ``profiles_unavailable``,
        ``no_verified_email``, or the sender's cause.
        """
        sender, missing_sender_cause = self._sender()
        if sender is None:
            self._record_unsent_type_change(change, missing_sender_cause)
            return NOT_CONFIGURED
        email, missing_email_cause = (
            (verified_email, NO_VERIFIED_EMAIL)
            if verified_email is not None
            else self._verified_email(change)
        )
        if email is None:
            self._record_unsent_type_change(change, missing_email_cause)
            return missing_email_cause
        cause = self._send(
            sender,
            to=email,
            template_alias=USER_TYPE_CHANGED_TEMPLATE_ALIAS,
            template_model=type_change_template_model(change, sender.app_url),
        )
        if cause is not None:
            self._record_unsent_type_change(change, cause)
        return cause

    @staticmethod
    def _record_unsent_type_change(change: UserTypeChangeEmail, cause: str) -> None:
        _record_unsent(
            TYPE_CHANGE_EMAIL_NOT_SENT_EVENT,
            {"user_id": str(change.user_id), "cause": cause},
        )
