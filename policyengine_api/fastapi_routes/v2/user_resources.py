"""Shared HTTP conventions for signed-in user-owned API v2 resources."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2.errors import (
    V2ErrorResponse,
    v2_error_response,
)
from policyengine_api.services.v2.associations.validators import (
    AssociationConflictError,
    AssociationLinkNotFoundError,
    AssociationNotFoundError,
    AssociationReferenceConflictError,
)
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)
from policyengine_api.services.v2.user_accounts.validators import (
    AccountIdentityDeletionError,
    AccountNotFoundError,
)
from policyengine_api.services.v2.user_households.validators import (
    AssociationHouseholdNotFoundError,
)
from policyengine_api.services.v2.user_policies.validators import (
    AssociationPolicyNotFoundError,
)


USER_RESOURCE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": V2ErrorResponse,
        "description": "The supplied references or countries contradict each other.",
    },
    401: {
        "model": V2ErrorResponse,
        "description": (
            "A valid bearer access token is required; the response carries "
            "WWW-Authenticate: Bearer."
        ),
    },
    403: {
        "model": V2ErrorResponse,
        "description": "Machine (client-credentials) principals are not permitted.",
    },
    404: {
        "model": V2ErrorResponse,
        "description": "The record does not exist or belongs to another user.",
    },
    409: {
        "model": V2ErrorResponse,
        "description": (
            "The change conflicts with stored state, such as a record maintained "
            "by the v1 saved-policy mirror or a duplicate client_ref."
        ),
    },
    422: {
        "model": V2ErrorResponse,
        "description": (
            "The request does not match the schema, or a referenced v1 artifact "
            "or linked record does not exist."
        ),
    },
    500: {
        "model": V2ErrorResponse,
        "description": "The operation could not be completed.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": "User authentication or persistence is unavailable.",
    },
}

OperationT = TypeVar("OperationT")


def user_resource_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    """Run one service call and map typed failures to secret-safe errors."""

    try:
        return operation()
    except AssociationReferenceConflictError as error:
        return v2_error_response(400, str(error))
    except (LegacyReferenceNotFoundError, AssociationLinkNotFoundError) as error:
        return v2_error_response(422, str(error))
    except (
        AssociationNotFoundError,
        AssociationPolicyNotFoundError,
        AssociationHouseholdNotFoundError,
        AccountNotFoundError,
    ) as error:
        return v2_error_response(404, str(error))
    except AssociationConflictError as error:
        return v2_error_response(409, str(error))
    except IntegrityError:
        return v2_error_response(409, "The record conflicts with stored state")
    except AccountIdentityDeletionError as error:
        return v2_error_response(502, str(error))
    except (V2ConfigurationError, SQLAlchemyError):
        return v2_error_response(503, "V2 user persistence is unavailable")
    except Exception:  # noqa: BLE001 - return a secret-safe typed error
        return v2_error_response(500, "V2 user operation failed")
