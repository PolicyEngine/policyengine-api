"""Pin every response and failure record of the v1 saved-policy write routes."""

from __future__ import annotations

from typing import NamedTuple
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from policyengine_api.data.v1_models import UserPolicy
from policyengine_api.routes import policy_routes
from policyengine_api.services.user_policy_mirroring import (
    UserPolicyMirrorUnavailableError,
)
from policyengine_api.services.user_policy_service import (
    UserPolicyCreateResult,
    UserPolicyPersistenceError,
    UserPolicyPersistenceFailureCategory,
    UserPolicyUpdateResult,
)

UNAVAILABLE_CONFIGURATION = {
    "status": "error",
    "message": "Policy persistence configuration is unavailable.",
}
MIRROR_UNAVAILABLE = {
    "message": "V2 saved-policy mirroring is unavailable; retry the same request."
}


def _row() -> UserPolicy:
    return UserPolicy(
        id=10,
        country_id="us",
        reform_id=2,
        reform_label="Reform",
        baseline_id=1,
        baseline_label="Current law",
        user_id="auth0|one",
        year="2026",
        geography="us",
        dataset=None,
        number_of_provisions=3,
        api_version="1.0.0",
        added_date=1,
        updated_date=2,
        budgetary_impact=None,
        type=None,
    )


def _body() -> dict[str, object]:
    return {
        "reform_id": 2,
        "baseline_id": 1,
        "user_id": "auth0|one",
        "year": "2026",
        "geography": "us",
        "number_of_provisions": 3,
        "api_version": "1.0.0",
        "added_date": 1,
        "updated_date": 2,
    }


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(policy_routes.policy_bp)
    return app.test_client()


@pytest.fixture
def write_source(monkeypatch) -> MagicMock:
    source = MagicMock(return_value="dual_write")
    monkeypatch.setattr(policy_routes, "get_v1_policy_write_source", source)
    monkeypatch.setattr(policy_routes, "get_v1_policy_read_source", MagicMock())
    return source


@pytest.fixture
def mirror(monkeypatch) -> MagicMock:
    mirror_events = MagicMock()
    monkeypatch.setattr(
        policy_routes,
        "mirror_pending_user_policy_events_after_commit",
        mirror_events,
    )
    return mirror_events


def _create(client):
    return client.post("/us/user-policy", json=_body())


def _update(client):
    return client.put("/us/user-policy", json={"id": 10, "reform_label": "Renamed"})


@pytest.mark.parametrize("send_request", [_create, _update])
@pytest.mark.parametrize("failing_source", ["write", "read"])
def test_invalid_persistence_configuration_is_unavailable(
    client,
    write_source: MagicMock,
    mirror: MagicMock,
    send_request,
    failing_source: str,
) -> None:
    if failing_source == "write":
        write_source.side_effect = ValueError("invalid")
    else:
        policy_routes.get_v1_policy_read_source.side_effect = ValueError("invalid")

    with (
        patch.object(
            policy_routes.user_policy_service, "create_or_get_user_policy"
        ) as create,
        patch.object(policy_routes.user_policy_service, "update_user_policy") as update,
    ):
        response = send_request(client)

    assert response.status_code == 503
    assert response.get_json() == UNAVAILABLE_CONFIGURATION
    create.assert_not_called()
    update.assert_not_called()
    mirror.assert_not_called()


class _PersistenceFailure(NamedTuple):
    category: UserPolicyPersistenceFailureCategory
    status_code: int
    message: str


class _SavedPolicyWrite(NamedTuple):
    send_request: object
    service_method: str
    operation: str
    legacy_id: int | None


@pytest.mark.parametrize(
    "failure",
    [
        _PersistenceFailure(
            UserPolicyPersistenceFailureCategory.TIMEOUT,
            503,
            "Policy database is temporarily unavailable; please try again later.",
        ),
        _PersistenceFailure(
            UserPolicyPersistenceFailureCategory.INTEGRITY,
            500,
            "Internal database error; please try again later.",
        ),
    ],
)
@pytest.mark.parametrize(
    "write",
    [
        _SavedPolicyWrite(_create, "create_or_get_user_policy", "create", None),
        _SavedPolicyWrite(_update, "update_user_policy", "update", 10),
    ],
)
def test_persistence_failures_log_one_record_and_return_a_safe_error(
    client,
    write_source: MagicMock,
    mirror: MagicMock,
    failure: _PersistenceFailure,
    write: _SavedPolicyWrite,
) -> None:
    write_source.return_value = "cloud_sql"
    category, status_code, message = failure

    with (
        patch.object(
            policy_routes.user_policy_service,
            write.service_method,
            side_effect=UserPolicyPersistenceError(category),
        ),
        patch.object(policy_routes, "logger") as logger,
        patch.object(policy_routes, "current_request_id", return_value="request-1"),
    ):
        response = write.send_request(client)

    assert response.status_code == status_code
    assert response.get_json() == {"message": message}
    record = dict(logger.log_struct.call_args.args[0])
    assert isinstance(record.pop("duration_ms"), float)
    expected = {
        "message": "V1 saved-policy persistence failed",
        "metric_name": "v1_user_policy_persistence_failures",
        "metric_value": 1,
        "resource": "user_policy",
        "operation": write.operation,
        "database_source": "cloud_sql",
        "configured_write_source": "cloud_sql",
        "country_id": "us",
        "legacy_user_policy_id": write.legacy_id,
        "request_id": "request-1",
        "outcome": "error",
        "failure_category": category.value,
        "http_status": status_code,
    }
    assert list(record) == list(expected)
    assert record == expected
    assert logger.log_struct.call_args.kwargs == {"severity": "ERROR"}
    mirror.assert_not_called()


@pytest.mark.usefixtures("write_source")
@pytest.mark.parametrize("send_request", [_create, _update])
def test_persistence_failure_survives_a_logging_failure(
    client,
    mirror: MagicMock,
    send_request,
) -> None:
    error = UserPolicyPersistenceError(UserPolicyPersistenceFailureCategory.DATABASE)

    with (
        patch.object(
            policy_routes.user_policy_service,
            "create_or_get_user_policy",
            side_effect=error,
        ),
        patch.object(
            policy_routes.user_policy_service,
            "update_user_policy",
            side_effect=error,
        ),
        patch.object(policy_routes.logger, "log_struct", side_effect=RuntimeError),
    ):
        response = send_request(client)

    assert response.status_code == 500
    assert response.get_json() == {
        "message": "Internal database error; please try again later."
    }
    mirror.assert_not_called()


@pytest.mark.usefixtures("write_source")
@pytest.mark.parametrize(
    "legacy_user_policy_id", [-1, 2_147_483_648, True, "10", 2_147_483_647, 0]
)
def test_failure_record_reports_only_a_safe_legacy_id(
    client,
    legacy_user_policy_id: object,
) -> None:
    error = UserPolicyPersistenceError(UserPolicyPersistenceFailureCategory.DATABASE)

    with (
        patch.object(
            policy_routes.user_policy_service,
            "update_user_policy",
            side_effect=error,
        ),
        patch.object(policy_routes, "logger") as logger,
    ):
        client.put(
            "/us/user-policy",
            json={"id": legacy_user_policy_id, "reform_label": "Renamed"},
        )

    record = logger.log_struct.call_args.args[0]
    expected = (
        legacy_user_policy_id
        if legacy_user_policy_id in {2_147_483_647, 0}
        and not isinstance(legacy_user_policy_id, bool)
        else None
    )
    assert record["legacy_user_policy_id"] == expected


def _creation(*, created: bool, mirror_revision: int | None):
    return UserPolicyCreateResult(
        user_policy=_row(),
        created=created,
        snapshot=None,
        mirror_revision=mirror_revision,
    )


def _update_result(mirror_revision: int | None):
    return UserPolicyUpdateResult(
        user_policy=_row(),
        snapshot=None,
        changed_fields=frozenset({"reform_label"}),
        mirror_revision=mirror_revision,
    )


@pytest.mark.usefixtures("write_source")
@pytest.mark.parametrize(
    "mirror_outcome",
    [
        (None, None),
        (3, UserPolicyMirrorUnavailableError("database secret")),
        (3, RuntimeError("unexpected secret")),
    ],
)
@pytest.mark.parametrize("send_request", [_create, _update])
def test_committed_write_without_a_mirror_is_mirror_unavailable(
    client,
    mirror: MagicMock,
    mirror_outcome: tuple[int | None, Exception | None],
    send_request,
) -> None:
    mirror_revision, mirror.side_effect = mirror_outcome

    with (
        patch.object(
            policy_routes.user_policy_service,
            "create_or_get_user_policy",
            return_value=_creation(created=True, mirror_revision=mirror_revision),
        ),
        patch.object(
            policy_routes.user_policy_service,
            "update_user_policy",
            return_value=_update_result(mirror_revision),
        ),
    ):
        response = send_request(client)

    assert response.status_code == 503
    assert response.get_json() == MIRROR_UNAVAILABLE
    assert mirror.call_count == int(mirror_revision is not None)


@pytest.mark.usefixtures("write_source")
@pytest.mark.parametrize(
    ("created", "status_code", "message"),
    [
        (True, 201, "Record created successfully"),
        (
            False,
            200,
            "The reform #2 / baseline #1 pair already exists for user auth0|one",
        ),
    ],
)
def test_mirrored_creation_returns_the_saved_policy(
    client,
    mirror: MagicMock,
    created,
    status_code: int,
    message: str,
) -> None:
    with patch.object(
        policy_routes.user_policy_service,
        "create_or_get_user_policy",
        return_value=_creation(created=created, mirror_revision=4),
    ):
        response = _create(client)

    assert response.status_code == status_code
    body = response.get_json()
    assert body["status"] == "ok"
    assert body["message"] == message
    if created:
        assert body["result"]["id"] == 10
        assert body["result"]["reform_label"] == "Reform"
    else:
        assert body["result"] == {"id": 10}
    assert mirror.call_args.args == ("us", 10)
    assert mirror.call_args.kwargs == {
        "through_revision": 4,
        "event_service": policy_routes.user_policy_service,
        "reform_snapshot_loader": policy_routes.policy_service.get_policy_snapshot,
    }


@pytest.mark.usefixtures("write_source")
def test_mirrored_update_returns_the_updated_id(
    client,
    mirror: MagicMock,
) -> None:
    with patch.object(
        policy_routes.user_policy_service,
        "update_user_policy",
        return_value=_update_result(5),
    ) as update:
        response = _update(client)

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "message": "Record updated successfully",
        "result": {"id": 10},
    }
    assert update.call_args.args == ("us", 10, {"reform_label": "Renamed"})
    assert update.call_args.kwargs == {"record_mirror_event": True}
    assert mirror.call_args.args == ("us", 10)
    assert mirror.call_args.kwargs == {
        "through_revision": 5,
        "event_service": policy_routes.user_policy_service,
        "reform_snapshot_loader": policy_routes.policy_service.get_policy_snapshot,
    }


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ([], "Request body must include an 'id' field."),
        ({"reform_label": "x"}, "Request body must include an 'id' field."),
        (
            {"id": 10, "user_id": "x", "reform_id": 3},
            "Request body contains unsupported fields: ['reform_id', 'user_id']",
        ),
        ({"id": 10}, "Request body must include at least one field to update."),
    ],
)
def test_invalid_update_requests_are_rejected_before_configuration(
    client,
    write_source: MagicMock,
    body: object,
    message: str,
) -> None:
    response = client.put("/us/user-policy", json=body)

    assert response.status_code == 400
    assert response.get_json() == {"message": message}
    write_source.assert_not_called()


@pytest.mark.usefixtures("write_source")
def test_update_of_an_unknown_saved_policy_is_not_found(
    client,
    mirror: MagicMock,
) -> None:
    with patch.object(
        policy_routes.user_policy_service, "update_user_policy", return_value=None
    ):
        response = _update(client)

    assert response.status_code == 404
    assert response.get_json() == {"message": "User policy #10 not found."}
    mirror.assert_not_called()
