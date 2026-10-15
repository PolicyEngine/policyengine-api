"""Characterization of the status, message and headers of each user-route failure."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, NamedTuple

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2 import user_resources
from policyengine_api.services.v2.associations.validators import (
    AssociationConflictError,
    AssociationLinkNotFoundError,
    AssociationNotFoundError,
    AssociationReferenceConflictError,
    MirrorOwnedAssociationError,
)
from policyengine_api.services.v2.identity.validators import (
    StandardUserRequiresSignInError,
)
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)
from policyengine_api.services.v2.user_accounts.validators import (
    AccountDeletionUnavailableError,
    AccountEditRequiresSignInError,
    AccountIdentityDeletionError,
    AccountNotFoundError,
)
from policyengine_api.services.v2.user_households.validators import (
    AssociationHouseholdNotFoundError,
    UserHouseholdNotFoundError,
)
from policyengine_api.services.v2.user_policies.validators import (
    AssociationPolicyNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

ERROR_MESSAGE = "typed failure message"


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def failure_records(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[logging.LogRecord]]:
    # Alembic tests run logging.config.fileConfig, which disables loggers that
    # already exist, so re-enable this one and record on it directly.
    handler = _RecordingHandler()
    monkeypatch.setattr(user_resources.logger, "disabled", False)
    user_resources.logger.addHandler(handler)
    yield handler.records
    user_resources.logger.removeHandler(handler)


def _failing(error: Exception):
    def operation() -> None:
        raise error

    return operation


class _FailureCase(NamedTuple):
    error: Exception
    status_code: int
    message: str
    challenge: str | None
    logged_event: str | None


@pytest.mark.parametrize(
    "case",
    [
        _FailureCase(
            StandardUserRequiresSignInError(ERROR_MESSAGE),
            401,
            ERROR_MESSAGE,
            "Bearer",
            None,
        ),
        _FailureCase(
            AccountEditRequiresSignInError(ERROR_MESSAGE),
            403,
            ERROR_MESSAGE,
            None,
            None,
        ),
        _FailureCase(
            AssociationReferenceConflictError(ERROR_MESSAGE),
            400,
            ERROR_MESSAGE,
            None,
            None,
        ),
        _FailureCase(
            LegacyReferenceNotFoundError(ERROR_MESSAGE), 422, ERROR_MESSAGE, None, None
        ),
        _FailureCase(
            AssociationLinkNotFoundError(ERROR_MESSAGE), 422, ERROR_MESSAGE, None, None
        ),
        _FailureCase(
            AssociationNotFoundError(ERROR_MESSAGE), 404, ERROR_MESSAGE, None, None
        ),
        _FailureCase(
            UserHouseholdNotFoundError(ERROR_MESSAGE), 404, ERROR_MESSAGE, None, None
        ),
        _FailureCase(
            AssociationPolicyNotFoundError(ERROR_MESSAGE),
            404,
            ERROR_MESSAGE,
            None,
            None,
        ),
        _FailureCase(
            AssociationHouseholdNotFoundError(ERROR_MESSAGE),
            404,
            ERROR_MESSAGE,
            None,
            None,
        ),
        _FailureCase(
            AccountNotFoundError(ERROR_MESSAGE), 404, ERROR_MESSAGE, None, None
        ),
        _FailureCase(
            AssociationConflictError(ERROR_MESSAGE), 409, ERROR_MESSAGE, None, None
        ),
        _FailureCase(
            MirrorOwnedAssociationError(ERROR_MESSAGE), 409, ERROR_MESSAGE, None, None
        ),
        _FailureCase(
            IntegrityError("INSERT", {}, Exception("duplicate")),
            409,
            "The record conflicts with stored state",
            None,
            None,
        ),
        _FailureCase(
            AccountIdentityDeletionError(ERROR_MESSAGE), 502, ERROR_MESSAGE, None, None
        ),
        _FailureCase(
            AccountDeletionUnavailableError(ERROR_MESSAGE),
            503,
            ERROR_MESSAGE,
            None,
            None,
        ),
        _FailureCase(
            V2ConfigurationError(ERROR_MESSAGE),
            503,
            "V2 user persistence is unavailable",
            None,
            "v2_user_persistence_unavailable",
        ),
        _FailureCase(
            OperationalError("SELECT", {}, Exception("down")),
            503,
            "V2 user persistence is unavailable",
            None,
            "v2_user_persistence_unavailable",
        ),
        _FailureCase(
            RuntimeError(ERROR_MESSAGE),
            500,
            "V2 user operation failed",
            None,
            "v2_user_operation_failed",
        ),
    ],
)
def test_each_failure_maps_to_its_typed_response(
    failure_records: list[logging.LogRecord], case: _FailureCase
) -> None:
    response = user_resources.user_resource_operation(_failing(case.error))

    assert response.status_code == case.status_code
    body = json.loads(response.body)
    assert body == {"status": "error", "message": case.message}
    assert response.headers.get("www-authenticate") == case.challenge
    assert [record.getMessage() for record in failure_records] == (
        [] if case.logged_event is None else [case.logged_event]
    )


def test_a_successful_operation_returns_its_result() -> None:
    assert user_resources.user_resource_operation(lambda: "result") == "result"
