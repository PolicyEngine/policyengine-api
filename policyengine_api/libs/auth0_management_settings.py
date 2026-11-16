"""Settings for the optional Auth0 Management API clients.

Two settings groups each configure one Management API machine-to-machine
client, ``AUTH0_MANAGEMENT_*`` for account deletion and
``AUTH0_USER_PROFILES_*`` for reading users' profiles; see
``policyengine_api.libs.auth0_management``, which uses them and re-exports
these names. Each group is all-or-none: a domain, a client ID, and exactly
one client-secret source (a direct value or a Secret Manager resource).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from policyengine_api.libs.user_auth import PUBLIC_API_AUTH_ISSUER_ENV

if TYPE_CHECKING:
    from collections.abc import Mapping

AUTH0_MANAGEMENT_DOMAIN_ENV = "AUTH0_MANAGEMENT_DOMAIN"
AUTH0_MANAGEMENT_CLIENT_ID_ENV = "AUTH0_MANAGEMENT_CLIENT_ID"
AUTH0_MANAGEMENT_CLIENT_SECRET_ENV = "AUTH0_MANAGEMENT_CLIENT_SECRET"  # noqa: S105  # an environment variable name, not a secret
AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE_ENV = "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE"  # noqa: S105  # an environment variable name, not a secret
AUTH0_MANAGEMENT_ENV_VARS = (
    AUTH0_MANAGEMENT_DOMAIN_ENV,
    AUTH0_MANAGEMENT_CLIENT_ID_ENV,
    AUTH0_MANAGEMENT_CLIENT_SECRET_ENV,
    AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE_ENV,
)
DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
SECRET_RESOURCE_PATTERN = re.compile(r"^projects/[^/]+/secrets/[^/]+/versions/[^/]+$")


@dataclass(frozen=True)
class Auth0ClientSettingNames:
    """The environment variables that configure one Management API client."""

    prefix: str
    # The configuration error's opening words when the group is incomplete.
    incomplete_message: str

    @property
    def domain(self) -> str:
        """Name the variable that holds the tenant's canonical domain."""
        return f"{self.prefix}_DOMAIN"

    @property
    def client_id(self) -> str:
        """Name the variable that holds the machine-to-machine client's ID."""
        return f"{self.prefix}_CLIENT_ID"

    @property
    def client_secret(self) -> str:
        """Name the variable that holds the client secret itself, for local use."""
        return f"{self.prefix}_CLIENT_SECRET"

    @property
    def client_secret_resource(self) -> str:
        """Name the variable that holds the client secret's Secret Manager version."""
        return f"{self.prefix}_CLIENT_SECRET_RESOURCE"


AUTH0_MANAGEMENT_SETTING_NAMES = Auth0ClientSettingNames(
    prefix="AUTH0_MANAGEMENT",
    incomplete_message="Auth0 Management API deletion is partially configured",
)
AUTH0_USER_PROFILE_SETTING_NAMES = Auth0ClientSettingNames(
    prefix="AUTH0_USER_PROFILES",
    incomplete_message="Auth0 user profile reads are partially configured",
)


class Auth0ManagementConfigurationError(RuntimeError):
    """Raised when the optional Management API settings are incomplete."""


@dataclass(frozen=True)
class Auth0ManagementSettings:
    """Validated Management API settings for one Auth0 tenant.

    Exactly one of ``client_secret`` and ``client_secret_resource`` (a Secret
    Manager version name) is set. The secret is kept out of ``repr``, and equal
    settings share one client, so its token is reused.
    """

    domain: str
    client_id: str
    client_secret: str = field(default="", repr=False)
    client_secret_resource: str = ""


def _load_client_settings(
    names: Auth0ClientSettingNames, environ: Mapping[str, str] | None
) -> Auth0ManagementSettings | None:
    """Return one group's complete settings, or ``None`` when it is absent."""
    values = os.environ if environ is None else environ
    domain = values.get(names.domain, "").strip()
    client_id = values.get(names.client_id, "").strip()
    client_secret = values.get(names.client_secret, "").strip()
    secret_resource = values.get(names.client_secret_resource, "").strip()
    if not any((domain, client_id, client_secret, secret_resource)):
        return None
    if client_secret and secret_resource:
        msg = (
            f"Set exactly one of {names.client_secret} or "
            f"{names.client_secret_resource}"
        )
        raise Auth0ManagementConfigurationError(msg)
    if not domain or not client_id or not (client_secret or secret_resource):
        msg = (
            f"{names.incomplete_message}: set {names.domain}, "
            f"{names.client_id}, and exactly one client-secret source"
        )
        raise Auth0ManagementConfigurationError(msg)
    if DOMAIN_PATTERN.fullmatch(domain) is None:
        msg = f"{names.domain} must be a bare host name"
        raise Auth0ManagementConfigurationError(msg)
    if secret_resource and SECRET_RESOURCE_PATTERN.fullmatch(secret_resource) is None:
        msg = f"{names.client_secret_resource} is invalid"
        raise Auth0ManagementConfigurationError(msg)
    return Auth0ManagementSettings(
        domain=domain,
        client_id=client_id,
        client_secret=client_secret,
        client_secret_resource=secret_resource,
    )


def load_auth0_management_settings(
    environ: Mapping[str, str] | None = None,
) -> Auth0ManagementSettings | None:
    """Return complete account-deletion settings, or ``None`` when absent."""
    return _load_client_settings(AUTH0_MANAGEMENT_SETTING_NAMES, environ)


def load_auth0_user_profile_settings(
    environ: Mapping[str, str] | None = None,
) -> Auth0ManagementSettings | None:
    """Return complete user-profile settings, or ``None`` when absent.

    Raise when they are set without ``PUBLIC_API_AUTH_ISSUER``: only
    identities from the users' issuer are users of the tenant, so without it
    profiles would be read for nobody.
    """
    values = os.environ if environ is None else environ
    settings = _load_client_settings(AUTH0_USER_PROFILE_SETTING_NAMES, values)
    if settings is not None and not values.get(PUBLIC_API_AUTH_ISSUER_ENV, "").strip():
        msg = (
            f"{AUTH0_USER_PROFILE_SETTING_NAMES.prefix}_* settings need "
            f"{PUBLIC_API_AUTH_ISSUER_ENV}: only identities from the users' "
            "issuer are looked up"
        )
        raise Auth0ManagementConfigurationError(msg)
    return settings
