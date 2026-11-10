"""HTTP support for routes that require a minimum user type.

A route requires a minimum type with a dependency built by
:func:`minimum_user_type_dependency`. A caller below the minimum gets 403,
whether it is signed in or a signed-out browser. The check reads the caller's
stored type and never provisions a user.
"""

# FastAPI evaluates the dependency's annotations when routes are registered,
# against this module's globals, so they are not postponed and their types are
# imported at runtime.
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from policyengine_api.data.v2.models import UserType
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.resource_service_protocols import (
    V2UserTypeResourceService,
)
from policyengine_api.fastapi_routes.v2.errors_support import (
    V2AuthenticationRequiredError,
    V2AuthenticationUnavailableError,
    V2PermissionDeniedError,
)
from policyengine_api.services.v2.identity.types import AccountPrincipal
from policyengine_api.services.v2.identity.validators import (
    StandardUserRequiresSignInError,
)
from policyengine_api.services.v2.user_types.validators import (
    UserTypeBelowMinimumError,
    UserTypeCheckUnavailableError,
)


def minimum_user_type_dependency(
    require_user: Callable[..., AccountPrincipal],
    service_factory: Callable[[], V2UserTypeResourceService],
    minimum: UserType,
) -> Callable[..., UserType]:
    """Build a dependency that admits callers of ``minimum`` or above.

    It returns the caller's type. Below ``minimum`` it raises
    V2PermissionDeniedError (403); a signed-out credential naming a signed-in
    user gets 401, and unavailable persistence 503.
    """

    def require_minimum_user_type(
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserType:
        try:
            return service_factory().require_minimum_user_type(
                principal=principal, minimum=minimum
            )
        except UserTypeBelowMinimumError as error:
            raise V2PermissionDeniedError(str(error)) from error
        except StandardUserRequiresSignInError as error:
            raise V2AuthenticationRequiredError(str(error)) from error
        except (V2ConfigurationError, UserTypeCheckUnavailableError) as error:
            msg = "V2 user persistence is unavailable"
            raise V2AuthenticationUnavailableError(msg) from error

    return require_minimum_user_type
