"""Log a failed economy request at a severity that matches its cause.

The daily telemetry error report groups the API's records at severity ERROR or
above (``.github/scripts/telemetry_error_issues``). A request the economy
routes refuse with a client error is not a failure of the API, so it is logged
at WARNING and forms no error group.
"""

from typing import Any

from policyengine_api.gcp_logging import logger
from policyengine_api.services.policy_service import PolicyNotFoundError
from policyengine_api.spm import SPMValidationError

REFUSED_REQUEST_SEVERITY = "WARNING"
FAILED_REQUEST_SEVERITY = "ERROR"


def is_refused_request(error: Exception, *, request_validated: bool) -> bool:
    """Return whether ``error`` refuses the request rather than failing it.

    A request is refused when it names a policy its country does not have
    (PolicyNotFoundError, which the routes answer with 404), or when request
    validation raises a ValueError, which they answer with 400: a year outside
    the country's years, an unknown region, a dataset, breakdown or SPM setting
    the API does not offer. Validation ends once the request's setup options
    are built, before any stored result is read or any job is sent, and
    ``request_validated`` says whether it had ended when ``error`` was raised.

    A ValueError raised after validation is not a refusal, although the route
    also answers it with 400: it reports a state the API did not expect, such
    as an unknown stored status, or a typed failure the simulation service
    stored for the request.
    """
    if isinstance(error, PolicyNotFoundError):
        return True
    return not request_validated and isinstance(error, ValueError)


def log_economy_request_failure(
    error: Exception,
    *,
    request_validated: bool,
    failure_message: str,
    refusal_message: str,
) -> None:
    """Log ``error``, which an economy request raised, before it is re-raised.

    A refusal (see ``is_refused_request``) is logged with ``refusal_message``
    at WARNING, and any other failure with ``failure_message`` at ERROR. Both
    record the exception's type, and an SPMValidationError's code, never its
    message.
    """
    refused = is_refused_request(error, request_validated=request_validated)
    record: dict[str, Any] = {
        "message": refusal_message if refused else failure_message,
        "error_type": type(error).__name__,
    }
    if isinstance(error, SPMValidationError):
        record["error_code"] = error.code
    logger.log_struct(
        record,
        severity=REFUSED_REQUEST_SEVERITY if refused else FAILED_REQUEST_SEVERITY,
    )
