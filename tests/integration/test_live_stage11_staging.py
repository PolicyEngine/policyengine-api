"""Stateful Stage 11 activation, event-replay, and rollback checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool


V1_ONLY_COUNTRIES = ("ca", "ng", "il")

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PHASE11_STAGING_EXERCISE") != "1",
    reason="live Stage 11 staging exercise was not explicitly selected",
)


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required for the live Stage 11 staging exercise")
    return value


def _state_path() -> Path:
    return Path(_required_environment("PHASE11_STATE_PATH"))


def _read_state() -> dict[str, object]:
    return json.loads(_state_path().read_text(encoding="utf-8"))


def _write_state(state: dict[str, object]) -> None:
    _state_path().write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _v1_engine():
    password = _required_environment("POLICYENGINE_DB_READONLY_PASSWORD")
    return create_engine(
        URL.create(
            "mysql+pymysql",
            username="policyengine_schema_reader",
            password=password,
            host="127.0.0.1",
            port=3307,
            database="policyengine",
        ),
        poolclass=NullPool,
    )


def _v2_engine():
    return create_engine(
        _required_environment("V2_MIGRATION_DATABASE_URL"),
        poolclass=NullPool,
    )


def _client(setting: str) -> httpx.Client:
    return httpx.Client(
        base_url=_required_environment(setting).rstrip("/"),
        timeout=90,
        follow_redirects=True,
    )


def _v1_document(country_id: str, amount: int) -> dict[str, object]:
    person = {
        "age": {"2026": 40},
        "employment_income": {"2026": amount},
    }
    members = {"members": ["adult"]}
    document: dict[str, object] = {
        "people": {"adult": person},
        "households": {"home": members},
    }
    if country_id == "uk":
        document["benunits"] = {"benefit unit": members}
    elif country_id == "us":
        document.update(
            {
                "families": {"family": members},
                "tax_units": {"tax unit": members},
                "spm_units": {"SPM unit": members},
                "marital_units": {"marital unit": members},
            }
        )
    return document


def _normalized_document(amount: int) -> dict[str, object]:
    memberships = {
        "household": "household-1",
        "family": "family-1",
        "tax_unit": "tax-unit-1",
        "spm_unit": "spm-unit-1",
        "marital_unit": "marital-unit-1",
    }
    document: dict[str, object] = {
        "people": [
            {
                "id": "person-1",
                "values": {
                    "age": {"2026": 40},
                    "employment_income": {"2026": amount},
                },
                "memberships": memberships,
            }
        ]
    }
    for collection, identifier in memberships.items():
        document[collection] = [{"id": identifier, "values": {}}]
    return document


def _v1_id_by_label(v1_engine, label: str) -> int:
    with v1_engine.connect() as connection:
        value = connection.scalar(
            text(
                "SELECT id FROM household WHERE country_id = 'us' "
                "AND label = :label ORDER BY id DESC LIMIT 1"
            ),
            {"label": label},
        )
    assert value is not None
    return int(value)


def _mapping_id(v2_engine, country_id: str, legacy_id: int):
    with v2_engine.connect() as connection:
        return connection.scalar(
            text(
                "SELECT household_id FROM legacy_household_mappings "
                "WHERE country_id = :country_id AND legacy_household_id = :legacy_id"
            ),
            {"country_id": country_id, "legacy_id": legacy_id},
        )


def test_live_stage11_activation_and_controlled_failure(
    integration_probe_id: str,
) -> None:
    """Exercise native resources, immediate copying, and a retained failure."""

    probe_id = integration_probe_id.replace("/", "-")
    amount = 20_000 + int(uuid4().hex[:6], 16) % 500_000
    v1_engine = _v1_engine()
    v2_engine = _v2_engine()
    evidence: dict[str, object] = {
        "environment": "staging",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "probe_id": probe_id,
        "revisions": {
            "cloud_sql_only": _required_environment("PHASE11_CLOUD_SQL_REVISION"),
            "dual_write": _required_environment("PHASE11_DUAL_WRITE_REVISION"),
            "controlled_failure": _required_environment("PHASE11_FAILURE_REVISION"),
        },
        "activation_selectors": {
            "ROUTE_IMPL_HOUSEHOLD": "flask_fallback",
            "DB_READ_HOUSEHOLD": "cloud_sql",
            "DB_WRITE_HOUSEHOLD": "dual_write",
        },
        "status_summary": {},
    }
    try:
        native_payload = {
            "country_id": "us",
            "default_year": 2026,
            "household_data": _normalized_document(amount + 1),
        }
        replacement_payload = {
            **native_payload,
            "household_data": _normalized_document(amount + 2),
        }
        concurrent_payload = {
            **native_payload,
            "household_data": _normalized_document(amount + 3),
        }
        user_uuid = uuid4()
        user_id = str(user_uuid)
        with _client("API_BASE_URL") as active_client:
            native = active_client.post(
                "/v2/households",
                params={"country_id": "us"},
                json=native_payload,
            )
            assert native.status_code == 201, native.text[:500]
            native_id = native.json()["result"]["item"]["id"]
            deduplicated = active_client.post(
                "/v2/households",
                params={"country_id": "us"},
                json=native_payload,
            )
            assert deduplicated.status_code == 200, deduplicated.text[:500]
            assert deduplicated.json()["result"]["item"]["id"] == native_id

            start_together = Barrier(2)

            def create_equivalent_household(_request_number: int):
                with _client("API_BASE_URL") as concurrent_client:
                    start_together.wait(timeout=10)
                    response = concurrent_client.post(
                        "/v2/households",
                        params={"country_id": "us"},
                        json=concurrent_payload,
                    )
                assert response.status_code in {200, 201}, response.text[:500]
                return response.status_code, response.json()["result"]["item"]["id"]

            with ThreadPoolExecutor(max_workers=2) as executor:
                concurrent_results = list(
                    executor.map(create_equivalent_household, range(2))
                )
            concurrent_statuses = sorted(result[0] for result in concurrent_results)
            concurrent_ids = {result[1] for result in concurrent_results}
            assert concurrent_statuses == [200, 201]
            assert len(concurrent_ids) == 1

            detail = active_client.get(
                f"/v2/households/{native_id}",
                params={"country_id": "us"},
            )
            assert detail.status_code == 200, detail.text[:500]
            listing = active_client.get(
                "/v2/households",
                params={"country_id": "us", "default_year": 2026, "limit": 100},
            )
            assert listing.status_code == 200, listing.text[:500]
            assert native_id in {
                item["id"] for item in listing.json()["result"]["items"]
            }
            replacement = active_client.post(
                "/v2/households",
                params={"country_id": "us"},
                json=replacement_payload,
            )
            assert replacement.status_code == 201, replacement.text[:500]
            replacement_id = replacement.json()["result"]["item"]["id"]

            with v2_engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO users (id, primary_country) VALUES (:id, 'us')"),
                    {"id": user_uuid},
                )

            association = active_client.post(
                "/v2/user-households",
                params={"country_id": "us"},
                json={
                    "country_id": "us",
                    "user_id": user_id,
                    "household_id": native_id,
                    "name": f"Stage 11 saved household {probe_id}",
                    "description": "Synthetic staging association",
                },
            )
            assert association.status_code == 201, association.text[:500]
            association_id = association.json()["result"]["item"]["id"]
            association_list = active_client.get(
                "/v2/user-households",
                params={"country_id": "us", "user_id": user_id},
            )
            assert association_list.status_code == 200, association_list.text[:500]
            assert association_id in {
                item["id"] for item in association_list.json()["result"]["items"]
            }
            reassigned = active_client.patch(
                f"/v2/user-households/{association_id}",
                params={"country_id": "us"},
                json={
                    "household_id": replacement_id,
                    "name": f"Stage 11 edited household {probe_id}",
                    "description": None,
                },
            )
            assert reassigned.status_code == 200, reassigned.text[:500]
            assert reassigned.json()["result"]["item"]["household_id"] == replacement_id
            deleted = active_client.delete(
                f"/v2/user-households/{association_id}",
                params={"country_id": "us"},
            )
            assert deleted.status_code == 204, deleted.text[:500]

        failed_label = f"Stage 11 retained failure {probe_id}"
        v1_payload = {
            "label": failed_label,
            "data": _v1_document("us", amount),
        }
        with _client("PHASE11_FAILURE_API_BASE_URL") as failure_client:
            failed = failure_client.post("/us/household", json=v1_payload)
            assert failed.status_code == 503, failed.text[:500]
        pending_legacy_id = _v1_id_by_label(v1_engine, failed_label)
        with v1_engine.connect() as connection:
            pending = connection.execute(
                text(
                    "SELECT processed_at FROM household_mirror_events "
                    "WHERE country_id = 'us' AND legacy_household_id = :legacy_id"
                ),
                {"legacy_id": pending_legacy_id},
            ).one()
        assert pending.processed_at is None
        assert _mapping_id(v2_engine, "us", pending_legacy_id) is None

        with _client("API_BASE_URL") as active_client:
            retried = active_client.post("/us/household", json=v1_payload)
            assert retried.status_code == 201, retried.text[:500]
            retry_legacy_id = retried.json()["result"]["household_id"]
            assert retry_legacy_id != pending_legacy_id
            retry_destination = _mapping_id(v2_engine, "us", retry_legacy_id)
            assert retry_destination is not None

            v1_detail = active_client.get(f"/us/household/{retry_legacy_id}")
            assert v1_detail.status_code == 200, v1_detail.text[:500]
            assert v1_detail.json()["result"]["id"] == retry_legacy_id
            assert isinstance(v1_detail.json()["result"]["id"], int)
            assert "v2_household_id" not in v1_detail.json()["result"]

            unsupported_put = active_client.put(
                f"/us/household/{retry_legacy_id}",
                json={
                    "label": f"Changed {failed_label}",
                    "data": _v1_document("us", amount + 3),
                },
            )
            assert unsupported_put.status_code == 405, unsupported_put.text[:500]
            unchanged = active_client.get(f"/us/household/{retry_legacy_id}")
            assert unchanged.json()["result"]["label"] == failed_label

            calculated = active_client.post(
                "/us/calculate",
                json={"household": _v1_document("us", amount), "policy": {}},
            )
            assert calculated.status_code == 200, calculated.text[:500]

            uk = active_client.post(
                "/uk/household",
                json={
                    "label": f"Stage 11 UK {probe_id}",
                    "data": _v1_document("uk", amount),
                },
            )
            assert uk.status_code == 201, uk.text[:500]
            uk_legacy_id = uk.json()["result"]["household_id"]
            assert _mapping_id(v2_engine, "uk", uk_legacy_id) is not None

        with _client("PHASE11_FAILURE_API_BASE_URL") as failure_client:
            for country_id in V1_ONLY_COUNTRIES:
                unsupported = failure_client.post(
                    f"/{country_id}/household",
                    json={
                        "label": f"Stage 11 {country_id} v1-only {probe_id}",
                        "data": {"people": {"adult": {}}},
                    },
                )
                assert unsupported.status_code == 201, unsupported.text[:500]
                unsupported_id = unsupported.json()["result"]["household_id"]
                with v1_engine.connect() as connection:
                    event_count = connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM household_mirror_events "
                            "WHERE country_id = :country_id "
                            "AND legacy_household_id = :legacy_id"
                        ),
                        {"country_id": country_id, "legacy_id": unsupported_id},
                    )
                assert event_count == 0

        evidence.update(
            {
                "pending_legacy_household_id": pending_legacy_id,
                "retry_legacy_household_id": retry_legacy_id,
                "retry_destination_household_id": str(retry_destination),
                "native_household_id": native_id,
                "concurrent_household_id": concurrent_ids.pop(),
                "replacement_household_id": replacement_id,
                "synthetic_user_id": user_id,
                "status_summary": {
                    "native_create": 201,
                    "native_deduplication": 200,
                    "native_concurrent_deduplication": concurrent_statuses,
                    "association_lifecycle": 204,
                    "controlled_supabase_failure": 503,
                    "client_retry_separate_source": 201,
                    "v1_put_removed": 405,
                    "v1_calculation": 200,
                    "uk_immediate_copy": 201,
                    "v1_only_country_writes": 201,
                },
            }
        )
        _write_state(evidence)
    finally:
        v1_engine.dispose()
        v2_engine.dispose()


def test_live_stage11_exact_event_replay() -> None:
    """Verify the authorized command completed the original retained event."""

    evidence = _read_state()
    legacy_id = int(evidence["pending_legacy_household_id"])
    expected_destination = evidence["retry_destination_household_id"]
    v1_engine = _v1_engine()
    v2_engine = _v2_engine()
    try:
        with v1_engine.connect() as connection:
            processed_at = connection.scalar(
                text(
                    "SELECT processed_at FROM household_mirror_events "
                    "WHERE country_id = 'us' AND legacy_household_id = :legacy_id"
                ),
                {"legacy_id": legacy_id},
            )
        assert processed_at is not None
        destination = _mapping_id(v2_engine, "us", legacy_id)
        assert str(destination) == expected_destination
        evidence["exact_event_replay"] = {
            "legacy_household_id": legacy_id,
            "destination_household_id": str(destination),
            "processed": True,
        }
        _write_state(evidence)
    finally:
        v1_engine.dispose()
        v2_engine.dispose()


def test_live_stage11_cloud_sql_only_rollback(integration_probe_id: str) -> None:
    """Verify rollback removes Supabase from new v1 household creation."""

    evidence = _read_state()
    probe_id = integration_probe_id.replace("/", "-")
    rollback_label = f"Stage 11 rollback {probe_id}"
    v1_engine = _v1_engine()
    v2_engine = _v2_engine()
    try:
        with _client("API_BASE_URL") as rollback_client:
            created = rollback_client.post(
                "/us/household",
                json={
                    "label": rollback_label,
                    "data": _v1_document("us", 999_001),
                },
            )
            assert created.status_code == 201, created.text[:500]
            legacy_id = created.json()["result"]["household_id"]
            unsupported_put = rollback_client.put(
                f"/us/household/{legacy_id}",
                json={"label": "Not applied", "data": {}},
            )
            assert unsupported_put.status_code == 405, unsupported_put.text[:500]

        with v1_engine.connect() as connection:
            event_count = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM household_mirror_events "
                    "WHERE country_id = 'us' AND legacy_household_id = :legacy_id"
                ),
                {"legacy_id": legacy_id},
            )
        assert event_count == 0
        assert _mapping_id(v2_engine, "us", legacy_id) is None
        assert (
            _mapping_id(
                v2_engine,
                "us",
                int(evidence["pending_legacy_household_id"]),
            )
            is not None
        )

        evidence["rollback"] = {
            "revision": _required_environment("PHASE11_CLOUD_SQL_REVISION"),
            "DB_WRITE_HOUSEHOLD": "cloud_sql",
            "legacy_household_id": legacy_id,
            "source_event_count": 0,
            "destination_mapping_count": 0,
            "prior_destination_retained": True,
            "v1_put_status": 405,
        }
        evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_state(evidence)
    finally:
        v1_engine.dispose()
        v2_engine.dispose()
