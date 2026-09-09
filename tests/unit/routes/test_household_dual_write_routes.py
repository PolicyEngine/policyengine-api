"""V1 household route tests for retained create-event copying to v2."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from flask import Flask
import pytest

from policyengine_api.data.v1_models import Household
from policyengine_api.routes.household_routes import household_bp
from policyengine_api.services.household_mirroring import (
    HouseholdMirrorUnavailableError,
)
from policyengine_api.services.household_service import HouseholdCreateResult
from policyengine_api.services.v2.households.types import LegacyHouseholdSnapshot


def _client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(household_bp)
    return app.test_client()


def _snapshot(country_id: str = "us") -> LegacyHouseholdSnapshot:
    return LegacyHouseholdSnapshot(
        country_id=country_id,
        legacy_household_id=42,
        label="Legacy household",
        api_version="1.0.0",
        household_json={"people": {"you": {"age": {"2026": 40}}}},
        source_household_hash="source-hash",
    )


def _creation(
    *,
    country_id: str = "us",
    mirrored: bool = True,
) -> HouseholdCreateResult:
    return HouseholdCreateResult(
        household=Household(
            id=42,
            country_id=country_id,
            label="Legacy household",
            api_version="1.0.0",
            household_json={"people": {"you": {"age": {"2026": 40}}}},
            household_hash="source-hash",
        ),
        snapshot=_snapshot(country_id) if mirrored else None,
        mirror_event_id=10 if mirrored else None,
    )


def _body() -> dict[str, object]:
    return {
        "label": "Legacy household",
        "data": {"people": {"you": {"age": {"2026": 40}}}},
    }


def test_cloud_sql_mode_preserves_response_and_creates_no_event_or_v2_call(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_HOUSEHOLD", "cloud_sql")
    with (
        patch(
            "policyengine_api.routes.household_routes.household_service.create_household",
            return_value=_creation(mirrored=False),
        ) as create,
        patch(
            "policyengine_api.routes.household_routes.process_household_event_after_commit"
        ) as copy_event,
    ):
        response = _client().post("/us/household", json=_body())

    assert response.status_code == 201
    assert response.json == {
        "status": "ok",
        "message": None,
        "result": {"household_id": 42},
    }
    create.assert_called_once_with(
        "us",
        {"people": {"you": {"age": {"2026": 40}}}},
        "Legacy household",
        record_mirror_event=False,
    )
    copy_event.assert_not_called()


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_dual_write_processes_exact_selected_event_before_success(
    monkeypatch,
    country_id: str,
) -> None:
    monkeypatch.setenv("DB_WRITE_HOUSEHOLD", "dual_write")
    events: list[str] = []
    create = MagicMock(
        side_effect=lambda *_args, **_kwargs: (
            events.append("cloud_sql") or _creation(country_id=country_id)
        )
    )
    copy_event = MagicMock(
        side_effect=lambda *_args, **_kwargs: events.append("supabase")
    )
    with (
        patch(
            "policyengine_api.routes.household_routes.household_service.create_household",
            create,
        ),
        patch(
            "policyengine_api.routes.household_routes.process_household_event_after_commit",
            copy_event,
        ),
    ):
        response = _client().post(f"/{country_id}/household", json=_body())

    assert response.status_code == 201
    assert response.json["result"] == {"household_id": 42}
    assert events == ["cloud_sql", "supabase"]
    assert create.call_args.kwargs == {"record_mirror_event": True}
    copy_event.assert_called_once()
    assert copy_event.call_args.args == (country_id, 42)


@pytest.mark.parametrize("country_id", ["ca", "ng", "il"])
def test_dual_write_keeps_other_v1_countries_entirely_on_cloud_sql(
    monkeypatch,
    country_id: str,
) -> None:
    monkeypatch.setenv("DB_WRITE_HOUSEHOLD", "dual_write")
    with (
        patch(
            "policyengine_api.routes.household_routes.household_service.create_household",
            return_value=_creation(country_id=country_id, mirrored=False),
        ) as create,
        patch(
            "policyengine_api.routes.household_routes.process_household_event_after_commit"
        ) as copy_event,
    ):
        response = _client().post(f"/{country_id}/household", json=_body())

    assert response.status_code == 201
    assert create.call_args.kwargs == {"record_mirror_event": False}
    copy_event.assert_not_called()


def test_destination_failure_reports_committed_source_and_does_not_claim_retry_repairs_it(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_HOUSEHOLD", "dual_write")
    with (
        patch(
            "policyengine_api.routes.household_routes.household_service.create_household",
            return_value=_creation(),
        ),
        patch(
            "policyengine_api.routes.household_routes.process_household_event_after_commit",
            side_effect=HouseholdMirrorUnavailableError("database credential secret"),
        ),
    ):
        response = _client().post("/us/household", json=_body())

    assert response.status_code == 503
    assert response.json["status"] == "error"
    assert "committed" in response.json["message"]
    assert "retained create event" in response.json["message"]
    assert "retry" not in response.json["message"].lower()
    assert "secret" not in response.text


def test_invalid_write_or_read_selector_stops_before_cloud_sql(monkeypatch) -> None:
    with patch(
        "policyengine_api.routes.household_routes.household_service.create_household"
    ) as create:
        monkeypatch.setenv("DB_WRITE_HOUSEHOLD", "supabase")
        invalid_write = _client().post("/us/household", json=_body())
        monkeypatch.setenv("DB_WRITE_HOUSEHOLD", "cloud_sql")
        monkeypatch.setenv("DB_READ_HOUSEHOLD", "read_compare")
        invalid_read = _client().post("/us/household", json=_body())

    assert invalid_write.status_code == 503
    assert invalid_read.status_code == 503
    create.assert_not_called()


def test_v1_get_uses_only_cloud_sql_and_put_is_unsupported(monkeypatch) -> None:
    monkeypatch.setenv("DB_READ_HOUSEHOLD", "cloud_sql")
    household = _creation(mirrored=False).household
    with patch(
        "policyengine_api.routes.household_routes.household_service.get_household",
        return_value=household,
    ) as read:
        response = _client().get("/us/household/42")
        unsupported = _client().put("/us/household/42", json=_body())

    assert response.status_code == 200
    assert response.json["result"]["id"] == 42
    assert unsupported.status_code == 405
    read.assert_called_once_with("us", 42)
