"""Database-independent validation for v2 identity resolution."""

from __future__ import annotations

from policyengine_api.data.v2.models import UserIdentity


class IdentityProvisioningError(RuntimeError):
    """Raised when a concurrent provisioning conflict leaves no stored identity."""


def require_concurrent_identity(identity: UserIdentity | None) -> UserIdentity:
    if identity is None:
        raise IdentityProvisioningError(
            "user identity provisioning conflict did not resolve to a stored row"
        )
    return identity
