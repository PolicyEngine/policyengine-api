"""The credentials the deployed-API tests send to the Public API.

The tests that call a deployed Public API (``API_BASE_URL``) through the
``api_client`` fixture send the CI server credential on every request: an
Auth0 client-credentials token of the Public API's CI client, in
``Authorization: Bearer``, as any PolicyEngine server does. push.yml requests
it once per job, from the Auth0 tenant of the environment it tests, with
``.github/scripts/request_ci_server_token.sh``, and passes it to the tests'
step as ``CI_SERVER_ACCESS_TOKEN``. Without it the tests fail instead of
skipping: once ``PUBLIC_API_SERVER_CREDENTIAL_REQUIRED=1``, the Public API
refuses every request without a server credential, apart from ``/health``,
``/v2/openapi.json`` and CORS preflights.

Since ``Authorization`` holds the server's own token, a signed-in user's token
is forwarded in ``PolicyEngine-User-Authorization``, as a PolicyEngine server
forwards a browser's (:func:`forwarded_user_headers`).
"""

from __future__ import annotations

import os
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
    """Return the CI server credential header, or raise without a token.

    Raise :class:`MissingServerCredentialError` when ``CI_SERVER_ACCESS_TOKEN``
    is unset or blank.
    """
    values = os.environ if environ is None else environ
    token = values.get(CI_SERVER_ACCESS_TOKEN_ENV, "").strip()
    if not token:
        msg = (
            f"{CI_SERVER_ACCESS_TOKEN_ENV} is not set: the deployed-API tests "
            "send the CI server credential on every request. In GitHub Actions, "
            "request it in the job with .github/scripts/request_ci_server_token.sh "
            f"and pass its output to this step as {CI_SERVER_ACCESS_TOKEN_ENV}."
        )
        raise MissingServerCredentialError(msg)
    return {"Authorization": f"Bearer {token}"}


def forwarded_user_headers(user_token: str) -> dict[str, str]:
    """Return the header that forwards a signed-in user's access token."""
    return {FORWARDED_USER_AUTHORIZATION_HEADER: f"Bearer {user_token}"}
