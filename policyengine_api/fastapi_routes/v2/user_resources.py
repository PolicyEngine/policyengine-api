"""Shared HTTP conventions for signed-in user-owned API v2 resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastapi import Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2.errors import (
    V2ErrorResponse,
    V2RequestTooLargeError,
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


MAXIMUM_USER_WRITE_REQUEST_BYTES = 256 * 1024
MAXIMUM_USER_IMPORT_REQUEST_BYTES = 1024 * 1024


def request_size_limit(
    maximum_bytes: int, *, label: str
) -> Callable[[Request], Awaitable[None]]:
    """Build a dependency that bounds declared and actual request body bytes.

    It runs after the router-level authentication dependency, so an
    unauthenticated request still gets 401 first.
    """

    async def enforce(request: Request) -> None:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as error:
                raise V2RequestTooLargeError(
                    "Request Content-Length is invalid"
                ) from error
            if declared_length > maximum_bytes:
                raise V2RequestTooLargeError(f"Request body exceeds {label}")
        if len(await request.body()) > maximum_bytes:
            raise V2RequestTooLargeError(f"Request body exceeds {label}")

    return enforce


enforce_user_write_request_size = request_size_limit(
    MAXIMUM_USER_WRITE_REQUEST_BYTES, label="256 KiB"
)
enforce_user_import_request_size = request_size_limit(
    MAXIMUM_USER_IMPORT_REQUEST_BYTES, label="1 MiB"
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
    413: {
        "model": V2ErrorResponse,
        "description": (
            "The request body exceeds 256 KiB (1 MiB for POST /v2/me/imports)."
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
