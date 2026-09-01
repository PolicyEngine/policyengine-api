"""V1 saved-policy route tests for immediate v2 association mirroring."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from flask import Flask
import pytest
from sqlalchemy.exc import (
    IntegrityError,
    OperationalError,
    SQLAlchemyError,
    TimeoutError as SQLAlchemyTimeoutError,
)

from policyengine_api.data.v1_models import UserPolicy
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
)
from policyengine_api.services.v2.user_policies.legacy_translation import (
    LegacyUserPolicySnapshot,
)
from policyengine_api.routes.policy_routes import policy_bp
from policyengine_api.services.user_policy_mirroring import (
    UserPolicyMirrorUnavailableError,
)
from policyengine_api.services.user_policy_service import (
    UserPolicyCreateResult,
    UserPolicyPersistenceError,
    UserPolicyUpdateResult,
)


def _client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(policy_bp)
    return app.test_client()


def _row(*, reform_label: str | None = "Reform", year: str = "2026"):
    return UserPolicy(
        id=10,
        country_id="us",
        reform_id=2,
        reform_label=reform_label,
        baseline_id=1,
        baseline_label="Current law",
        user_id="auth0|one",
        year=year,
        geography="us",
        dataset="enhanced_cps_2024",
        number_of_provisions=3,
        api_version="1.0.0",
        added_date=1,
        updated_date=2,
        budgetary_impact=None,
        type=None,
    )


def _snapshot(*, reform_label: str | None = "Reform", year: str = "2026"):
    return LegacyUserPolicySnapshot(
        country_id="us",
        legacy_user_policy_id=10,
        reform_id=2,
        reform_label=reform_label,
        baseline_id=1,
        baseline_label="Current law",
        user_id="auth0|one",
        year=year,
        geography="us",
        dataset="enhanced_cps_2024",
        number_of_provisions=3,
        api_version="1.0.0",
        added_date=1,
        updated_date=2,
        budgetary_impact=None,
        type=None,
    )


def _reform_snapshot():
    return LegacyPolicySnapshot(
        country_id="us",
        legacy_policy_id=2,
        label="Ignored core label",
        api_version="1.0.0",
        policy_json={"gov.example.rate": {"2026": 0.2}},
        source_policy_hash="legacy/base64+hash=",
    )


def _creation(*, created=True, reform_label="Reform", mirror_revision=1):
    return UserPolicyCreateResult(
        user_policy=_row(reform_label=reform_label),
        created=created,
        snapshot=_snapshot(reform_label=reform_label),
        mirror_revision=mirror_revision,
    )


def _body(*, reform_label="Reform") -> dict[str, object]:
    return {
        "reform_id": 2,
        "reform_label": reform_label,
        "baseline_id": 1,
        "baseline_label": "Current law",
        "user_id": "auth0|one",
        "year": "2026",
        "geography": "us",
        "dataset": "enhanced_cps_2024",
        "number_of_provisions": 3,
        "api_version": "1.0.0",
        "added_date": 1,
        "updated_date": 2,
        "budgetary_impact": None,
        "type": None,
    }


def test_cloud_sql_mode_preserves_create_without_association_mirror(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "cloud_sql")
    with (
        patch(
            "policyengine_api.routes.policy_routes.user_policy_service.create_or_get_user_policy",
            return_value=_creation(),
        ),
        patch(
            "policyengine_api.routes.policy_routes."
            "mirror_pending_user_policy_events_after_commit"
        ) as mirror,
        patch(
            "policyengine_api.routes.policy_routes.policy_service.get_policy_snapshot"
        ) as get_reform,
    ):
        response = _client().post("/us/user-policy", json=_body())

    assert response.status_code == 201
    assert response.json["result"]["id"] == 10
    assert "v2" not in response.json["result"]
    mirror.assert_not_called()
    get_reform.assert_not_called()


def test_dual_write_mirrors_new_existing_and_unlabeled_saved_policies(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "dual_write")
    for created, label, expected_status in (
        (True, "Reform", 201),
        (False, "Reform", 200),
        (True, None, 201),
    ):
        creation = _creation(created=created, reform_label=label)
        with (
            patch(
                "policyengine_api.routes.policy_routes.user_policy_service.create_or_get_user_policy",
                return_value=creation,
            ),
            patch(
                "policyengine_api.routes.policy_routes.policy_service.get_policy_snapshot",
                return_value=_reform_snapshot(),
            ),
            patch(
                "policyengine_api.routes.policy_routes."
                "mirror_pending_user_policy_events_after_commit"
            ) as mirror,
        ):
            response = _client().post(
                "/us/user-policy",
                json=_body(reform_label=label),
            )

        assert response.status_code == expected_status
        assert response.json["result"]["id"] == 10
        assert "v2" not in response.json["result"]
        mirror.assert_called_once()
        assert mirror.call_args.args == ("us", 10)
        assert mirror.call_args.kwargs["through_revision"] == 1


def test_saved_policy_mirror_failure_returns_503_and_retry_completes(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "dual_write")
    creation = _creation(created=False)
    with (
        patch(
            "policyengine_api.routes.policy_routes.user_policy_service.create_or_get_user_policy",
            return_value=creation,
        ) as create,
        patch(
            "policyengine_api.routes.policy_routes.policy_service.get_policy_snapshot",
            return_value=_reform_snapshot(),
        ),
        patch(
            "policyengine_api.routes.policy_routes."
            "mirror_pending_user_policy_events_after_commit",
            side_effect=[
                UserPolicyMirrorUnavailableError("database credential secret"),
                MagicMock(),
            ],
        ) as mirror,
    ):
        first = _client().post("/us/user-policy", json=_body())
        retry = _client().post("/us/user-policy", json=_body())

    assert first.status_code == 503
    assert first.json == {
        "message": "V2 saved-policy mirroring is unavailable; retry the same request."
    }
    assert "secret" not in first.text
    assert retry.status_code == 200
    assert retry.json["result"] == {"id": 10}
    assert create.call_count == mirror.call_count == 2


@pytest.mark.parametrize(
    (
        "method",
        "service_method",
        "body",
        "error",
        "expected_status",
        "expected_category",
        "expected_operation",
    ),
    (
        (
            "post",
            "create_or_get_user_policy",
            _body(),
            SQLAlchemyTimeoutError("credential=timeout-secret"),
            503,
            "timeout",
            "create",
        ),
        (
            "put",
            "update_user_policy",
            {"id": 10, "reform_label": "Renamed"},
            OperationalError(
                "UPDATE user_policies SET secret=:secret",
                {"secret": "bound-parameter-secret"},
                RuntimeError("driver-secret"),
            ),
            503,
            "unavailable",
            "update",
        ),
        (
            "post",
            "create_or_get_user_policy",
            _body(),
            IntegrityError(
                "INSERT caller-private-data",
                {"user_id": "caller-private-data"},
                RuntimeError("integrity-secret"),
            ),
            500,
            "integrity",
            "create",
        ),
        (
            "put",
            "update_user_policy",
            {"id": 10, "year": "2027"},
            SQLAlchemyError("database-secret"),
            500,
            "database",
            "update",
        ),
        (
            "post",
            "create_or_get_user_policy",
            _body(),
            RuntimeError("unexpected-secret"),
            500,
            "unexpected",
            "create",
        ),
        (
            "put",
            "update_user_policy",
            {"id": "caller-id-secret", "year": "2027"},
            RuntimeError("unexpected-secret"),
            500,
            "unexpected",
            "update",
        ),
    ),
)
def test_saved_policy_persistence_failures_use_allowlisted_records(
    monkeypatch,
    method,
    service_method,
    body,
    error,
    expected_status,
    expected_category,
    expected_operation,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "cloud_sql")
    with (
        patch(
            f"policyengine_api.routes.policy_routes.user_policy_service.{service_method}",
            side_effect=UserPolicyPersistenceError.from_exception(error),
        ),
        patch(
            "policyengine_api.routes.policy_routes.current_request_id",
            return_value="request-123",
        ),
        patch("policyengine_api.routes.policy_routes.logger.log_struct") as log_struct,
    ):
        response = getattr(_client(), method)("/us/user-policy", json=body)

    expected_message = (
        "Policy database is temporarily unavailable; please try again later."
        if expected_status == 503
        else "Internal database error; please try again later."
    )
    assert response.status_code == expected_status
    assert response.json == {"message": expected_message}

    log_struct.assert_called_once()
    assert log_struct.call_args.kwargs == {"severity": "ERROR"}
    payload = log_struct.call_args.args[0]
    assert set(payload) == {
        "message",
        "metric_name",
        "metric_value",
        "resource",
        "operation",
        "database_source",
        "configured_write_source",
        "country_id",
        "legacy_user_policy_id",
        "request_id",
        "outcome",
        "failure_category",
        "http_status",
        "duration_ms",
    }
    assert payload["operation"] == expected_operation
    assert payload["failure_category"] == expected_category
    assert payload["http_status"] == expected_status
    assert payload["request_id"] == "request-123"
    supplied_id = body.get("id")
    expected_logged_id = (
        supplied_id
        if isinstance(supplied_id, int)
        and not isinstance(supplied_id, bool)
        and 0 <= supplied_id <= 2_147_483_647
        else None
    )
    assert payload["legacy_user_policy_id"] == expected_logged_id

    serialized_record = json.dumps(payload, sort_keys=True)
    for private_value in (
        "timeout-secret",
        "bound-parameter-secret",
        "driver-secret",
        "caller-private-data",
        "integrity-secret",
        "database-secret",
        "unexpected-secret",
        "caller-id-secret",
    ):
        assert private_value not in response.text
        assert private_value not in serialized_record


def test_update_mirrors_projected_and_v1_only_changes_before_success(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "dual_write")
    for payload, snapshot in (
        ({"reform_label": "Renamed"}, _snapshot(reform_label="Renamed")),
        ({"year": "2027"}, _snapshot(year="2027")),
    ):
        update = UserPolicyUpdateResult(
            user_policy=_row(
                reform_label=snapshot.reform_label,
                year=snapshot.year,
            ),
            snapshot=snapshot,
            changed_fields=frozenset(payload),
            mirror_revision=1,
        )
        with (
            patch(
                "policyengine_api.routes.policy_routes.user_policy_service.update_user_policy",
                return_value=update,
            ),
            patch(
                "policyengine_api.routes.policy_routes.policy_service.get_policy_snapshot",
                return_value=_reform_snapshot(),
            ),
            patch(
                "policyengine_api.routes.policy_routes."
                "mirror_pending_user_policy_events_after_commit"
            ) as mirror,
        ):
            response = _client().put(
                "/us/user-policy",
                json={"id": 10, **payload},
            )

        assert response.status_code == 200
        assert response.json["result"] == {"id": 10}
        assert mirror.call_args.args == ("us", 10)
        assert mirror.call_args.kwargs["through_revision"] == 1


def test_saved_policy_reads_remain_cloud_sql_only(monkeypatch) -> None:
    monkeypatch.setenv("DB_READ_POLICY", "cloud_sql")
    with (
        patch(
            "policyengine_api.routes.policy_routes.user_policy_service.list_user_policies",
            return_value=[_row()],
        ) as list_rows,
        patch(
            "policyengine_api.routes.policy_routes."
            "mirror_pending_user_policy_events_after_commit"
        ) as mirror,
    ):
        response = _client().get("/us/user-policy/auth0|one")

    assert response.status_code == 200
    assert response.json["result"][0]["id"] == 10
    list_rows.assert_called_once_with("us", "auth0|one")
    mirror.assert_not_called()

    monkeypatch.setenv("DB_READ_POLICY", "supabase")
    with patch(
        "policyengine_api.routes.policy_routes.user_policy_service.list_user_policies"
    ) as invalid_list:
        invalid = _client().get("/us/user-policy/auth0|one")

    assert invalid.status_code == 503
    invalid_list.assert_not_called()


def test_v1_saved_policy_delete_is_not_added() -> None:
    response = _client().delete("/us/user-policy", json={"id": 10})

    assert response.status_code == 405
