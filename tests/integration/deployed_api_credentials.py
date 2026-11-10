"""Placeholder for the headers the deployed-API tests send (tests come first)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

CI_SERVER_ACCESS_TOKEN_ENV = "CI_SERVER_ACCESS_TOKEN"
FORWARDED_USER_AUTHORIZATION_HEADER = "PolicyEngine-User-Authorization"


class MissingServerCredentialError(RuntimeError):
    """Raised when a deployed test has no CI server token."""


def server_credential_headers(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return no headers yet."""
    del environ
    return {}


def forwarded_user_headers(user_token: str) -> dict[str, str]:
    """Return no headers yet."""
    del user_token
    return {}
