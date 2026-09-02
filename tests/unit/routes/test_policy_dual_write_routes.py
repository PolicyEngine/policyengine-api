"""V1 policy route tests for immediate post-commit v2 mirroring."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from flask import Flask
import pytest

from policyengine_api.data.v1_models import Policy
from policyengine_api.services.v2.policies.types import LegacyPolicySnapshot
from policyengine_api.routes.policy_routes import policy_bp
from policyengine_api.services.policy_mirroring import PolicyMirrorUnavailableError
from policyengine_api.services.policy_service import PolicySetResult


def _client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(policy_bp)
    return app.test_client()


def _snapshot(country_id: str = "us") -> LegacyPolicySnapshot:
    return LegacyPolicySnapshot(
        country_id=country_id,
        legacy_policy_id=42,
        label="Legacy label",
        api_version="1.0.0",
        policy_json={"gov.example.rate": {"2026": 0.2}},
        source_policy_hash="legacy/base64+hash=",
    )


def _creation(
    *,
    existing: bool = False,
    country_id: str = "us",
) -> PolicySetResult:
    return PolicySetResult(
        policy_id=42,
        message="Policy already exists" if existing else "Policy created",
        is_existing_policy=existing,
        snapshot=_snapshot(country_id),
    )


def _body() -> dict[str, object]:
    return {
        "label": "Legacy label",
        "data": {"gov.example.rate": {"2026": 0.2}},
    }


def test_cloud_sql_mode_preserves_v1_create_response_without_mirroring(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "cloud_sql")
    with (
        patch(
            "policyengine_api.routes.policy_routes.policy_service.set_policy",
            return_value=_creation(),
        ) as set_policy,
        patch(
            "policyengine_api.routes.policy_routes.mirror_policy_after_commit"
        ) as mirror,
    ):
        response = _client().post("/us/policy", json=_body())

    assert response.status_code == 201
    assert response.json == {
        "status": "ok",
        "message": "Policy created",
        "result": {"policy_id": 42},
    }
    set_policy.assert_called_once_with(
        "us",
        "Legacy label",
        {"gov.example.rate": {"2026": 0.2}},
        prepare_for_mirroring=False,
    )
    mirror.assert_not_called()


@pytest.mark.parametrize("country_id", ("us", "uk"))
def test_dual_write_mirrors_new_and_existing_rows_before_success(
    monkeypatch,
    country_id,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "dual_write")
    for existing, expected_status in ((False, 201), (True, 200)):
        events: list[str] = []
        service = MagicMock(
            side_effect=lambda *_args, **_kwargs: (
                events.append("cloud_sql")
                or _creation(existing=existing, country_id=country_id)
            )
        )
        mirror = MagicMock(side_effect=lambda _snapshot: events.append("supabase"))
        with (
            patch(
                "policyengine_api.routes.policy_routes.policy_service.set_policy",
                service,
            ),
            patch(
                "policyengine_api.routes.policy_routes.mirror_policy_after_commit",
                mirror,
            ),
        ):
            response = _client().post(f"/{country_id}/policy", json=_body())

        assert response.status_code == expected_status
        assert response.json["result"] == {"policy_id": 42}
        assert "v2" not in response.json["result"]
        assert events == ["cloud_sql", "supabase"]
        assert service.call_args.kwargs == {"prepare_for_mirroring": True}
        mirror.assert_called_once_with(_snapshot(country_id))


@pytest.mark.parametrize("country_id", ("ca", "ng", "il"))
def test_dual_write_preserves_v1_only_policy_writes_for_non_v2_countries(
    monkeypatch,
    country_id,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "dual_write")
    creation = PolicySetResult(
        policy_id=42,
        message="Policy created",
        is_existing_policy=False,
        snapshot=None,
    )
    with (
        patch(
            "policyengine_api.routes.policy_routes.policy_service.set_policy",
            return_value=creation,
        ) as set_policy,
        patch(
            "policyengine_api.routes.policy_routes.mirror_policy_after_commit"
        ) as mirror,
    ):
        response = _client().post(f"/{country_id}/policy", json=_body())

    assert response.status_code == 201
    assert response.json["result"] == {"policy_id": 42}
    set_policy.assert_called_once_with(
        country_id,
        "Legacy label",
        {"gov.example.rate": {"2026": 0.2}},
        prepare_for_mirroring=False,
    )
    mirror.assert_not_called()


def test_mirror_failure_returns_503_and_identical_retry_completes(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "dual_write")
    creation = _creation(existing=True)
    with (
        patch(
            "policyengine_api.routes.policy_routes.policy_service.set_policy",
            return_value=creation,
        ) as set_policy,
        patch(
            "policyengine_api.routes.policy_routes.mirror_policy_after_commit",
            side_effect=[
                PolicyMirrorUnavailableError("database credential secret"),
                MagicMock(),
            ],
        ) as mirror,
    ):
        first = _client().post("/us/policy", json=_body())
        retry = _client().post("/us/policy", json=_body())

    assert first.status_code == 503
    assert first.json == {
        "status": "error",
        "message": "V2 policy mirroring is unavailable; retry the same request.",
    }
    assert "secret" not in first.text
    assert retry.status_code == 200
    assert retry.json["result"] == {"policy_id": 42}
    assert set_policy.call_count == 2
    assert mirror.call_count == 2


def test_supabase_only_v1_write_selection_is_rejected_before_cloud_sql(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "supabase")
    with patch(
        "policyengine_api.routes.policy_routes.policy_service.set_policy"
    ) as set_policy:
        response = _client().post("/us/policy", json=_body())

    assert response.status_code == 503
    assert response.json["status"] == "error"
    set_policy.assert_not_called()


def test_v1_policy_reads_require_cloud_sql_and_never_invoke_v2(
    monkeypatch,
) -> None:
    policy = Policy(
        id=42,
        country_id="us",
        label="Legacy label",
        api_version="1.0.0",
        policy_json={"gov.example.rate": {"2026": 0.2}},
        policy_hash="legacy/base64+hash=",
    )
    monkeypatch.setenv("DB_READ_POLICY", "cloud_sql")
    with (
        patch(
            "policyengine_api.routes.policy_routes.policy_service.get_policy",
            return_value=policy,
        ) as get_policy,
        patch(
            "policyengine_api.routes.policy_routes.mirror_policy_after_commit"
        ) as mirror,
    ):
        response = _client().get("/us/policy/42")

    assert response.status_code == 200
    assert json.loads(response.text)["result"]["id"] == 42
    get_policy.assert_called_once_with("us", 42)
    mirror.assert_not_called()

    monkeypatch.setenv("DB_READ_POLICY", "read_compare")
    with patch(
        "policyengine_api.routes.policy_routes.policy_service.get_policy"
    ) as invalid_get:
        invalid = _client().get("/us/policy/42")

    assert invalid.status_code == 503
    invalid_get.assert_not_called()


def test_policy_search_failure_does_not_expose_exception_details(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_READ_POLICY", "cloud_sql")
    with patch(
        "policyengine_api.routes.policy_routes.policy_service.search_policies",
        side_effect=RuntimeError("database-credential-secret"),
    ):
        response = _client().get("/us/policies?query=example")

    assert response.status_code == 500
    assert response.json == {
        "status": "error",
        "message": "Internal server error; please try again later.",
    }
    assert "database-credential-secret" not in response.text
