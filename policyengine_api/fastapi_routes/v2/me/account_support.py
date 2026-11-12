"""HTTP support the account routes (/v2/me) share."""

# FastAPI evaluates the dependencies' annotations when routes are registered,
# against this module's globals, so they are not postponed and their types are
# imported at runtime.
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2AccountResourceService,
    _default_v2_account_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.user_auth_support import (
    require_signed_in_principal,
)
from policyengine_api.query_parameters import CountryQuery
from policyengine_api.services.v2.identity.types import (
    AccountPrincipal,
    UserPrincipal,
)

CountryQueryDependency = Annotated[
    CountryQuery, Depends(query_dependency(CountryQuery))
]


def account_service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2AccountResourceService]:
    """Return the account service factory, or the default one."""
    if dependencies.v2_account_service_factory is not None:
        return dependencies.v2_account_service_factory
    return _default_v2_account_service_factory


def signed_in_user_dependency(
    require_user: Callable[..., AccountPrincipal],
) -> Callable[..., UserPrincipal]:
    """Build a dependency that admits only a signed-in principal of ``require_user``."""

    def require_signed_in_user(
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserPrincipal:
        return require_signed_in_principal(principal)

    return require_signed_in_user
