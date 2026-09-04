"""Stateful activation and rollback checks for the isolated staging databases."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool


V1_ONLY_COUNTRIES = ("ca", "ng", "il")
SYNTHETIC_PARAMETER = "gov.states.ut.tax.income.rate"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PHASE10_STAGING_EXERCISE") != "1",
    reason="live Phase 10 staging exercise was not explicitly selected",
)


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required for the live Phase 10 staging exercise")
    return value


def _state_path() -> Path:
    return Path(_required_environment("PHASE10_STATE_PATH"))


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


def _counts(v1_engine, v2_engine) -> dict[str, int]:
    with v1_engine.connect() as connection:
        v1_counts = {
            "v1_policies": connection.scalar(text("SELECT COUNT(*) FROM policy")),
            "v1_user_policies": connection.scalar(
                text("SELECT COUNT(*) FROM user_policies")
            ),
            "v1_pending_mirror_events": connection.scalar(
                text(
                    "SELECT COUNT(*) FROM user_policy_mirror_events "
                    "WHERE processed_at IS NULL"
                )
            ),
        }
    with v2_engine.connect() as connection:
        v2_counts = {
            "v2_policies": connection.scalar(text("SELECT COUNT(*) FROM policies")),
            "v2_user_policies": connection.scalar(
                text("SELECT COUNT(*) FROM user_policies")
            ),
            "v2_policy_mappings": connection.scalar(
                text("SELECT COUNT(*) FROM legacy_policy_mappings")
            ),
            "v2_user_policy_mappings": connection.scalar(
                text("SELECT COUNT(*) FROM legacy_user_policy_mappings")
            ),
        }
    return {key: int(value) for key, value in {**v1_counts, **v2_counts}.items()}


def _policy_payload(label: str, value: float) -> dict[str, object]:
    return {
        "label": label,
        "data": {
            SYNTHETIC_PARAMETER: {
                "2026-01-01.2100-12-31": value,
            }
        },
    }


def _saved_policy_payload(
    *, probe_id: str, reform_id: int, reform_label: str
) -> dict[str, object]:
    return {
        "reform_id": reform_id,
        "reform_label": reform_label,
        "baseline_id": reform_id,
        "baseline_label": "Synthetic staging baseline",
        "user_id": f"phase10-staging-{probe_id}",
        "year": "2026",
        "geography": "us",
        "dataset": "enhanced_cps_2024",
        "number_of_provisions": 1,
        "api_version": "1.0.0",
        "added_date": 1,
        "updated_date": 2,
        "budgetary_impact": None,
        "type": "phase10-staging",
    }


def _assert_v1_policy_identity(response: httpx.Response, expected_id: int) -> None:
    assert response.status_code == 200, response.text[:500]
    item = response.json()["result"]
    assert item["id"] == expected_id
    assert isinstance(item["id"], int)
    assert "uuid" not in item
    assert "v2_policy_id" not in item


def test_live_phase10_activation_failure_and_retry(integration_probe_id: str) -> None:
    """Activate immediate mirroring and prove deterministic retry semantics."""

    probe_id = integration_probe_id.replace("/", "-")
    unique_value = 0.04 + (int(uuid4().hex[:6], 16) % 5000) / 1_000_000
    v1_engine = _v1_engine()
    v2_engine = _v2_engine()
    evidence: dict[str, object] = {
        "environment": "staging",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "probe_id": probe_id,
        "revisions": {
            "cloud_sql_only": _required_environment("PHASE10_CLOUD_SQL_REVISION"),
            "dual_write": _required_environment("PHASE10_DUAL_WRITE_REVISION"),
            "controlled_failure": _required_environment("PHASE10_FAILURE_REVISION"),
        },
        "activation_selectors": {
            "ROUTE_IMPL_POLICY": "fastapi_native",
            "DB_READ_POLICY": "cloud_sql",
            "DB_WRITE_POLICY": "dual_write",
        },
        "status_summary": {},
    }
    try:
        evidence["counts_before"] = _counts(v1_engine, v2_engine)
        first_label = f"Phase 10 failure retry {probe_id}"
        first_payload = _policy_payload(first_label, unique_value)

        with _client("PHASE10_FAILURE_API_BASE_URL") as failure_client:
            failed = failure_client.post("/us/policy", json=first_payload)
            assert failed.status_code == 503, failed.text[:500]
            evidence["status_summary"]["controlled_supabase_failure"] = 503

        with _client("API_BASE_URL") as active_client:
            retried = active_client.post("/us/policy", json=first_payload)
            assert retried.status_code == 200, retried.text[:500]
            first_legacy_id = retried.json()["result"]["policy_id"]
            assert isinstance(first_legacy_id, int)
            evidence["status_summary"]["policy_retry"] = 200

            _assert_v1_policy_identity(
                active_client.get(f"/us/policy/{first_legacy_id}"),
                first_legacy_id,
            )

            with v2_engine.connect() as connection:
                first_v2_id = connection.scalar(
                    text(
                        "SELECT policy_id FROM legacy_policy_mappings "
                        "WHERE country_id = 'us' AND legacy_policy_id = :legacy_id"
                    ),
                    {"legacy_id": first_legacy_id},
                )
            assert first_v2_id is not None

            equivalent_payload = _policy_payload(
                f"Phase 10 equivalent label {probe_id}",
                unique_value,
            )
            equivalent = active_client.post("/us/policy", json=equivalent_payload)
            assert equivalent.status_code == 201, equivalent.text[:500]
            equivalent_legacy_id = equivalent.json()["result"]["policy_id"]
            with v2_engine.connect() as connection:
                equivalent_v2_id = connection.scalar(
                    text(
                        "SELECT policy_id FROM legacy_policy_mappings "
                        "WHERE country_id = 'us' AND legacy_policy_id = :legacy_id"
                    ),
                    {"legacy_id": equivalent_legacy_id},
                )
            assert equivalent_v2_id == first_v2_id
            evidence["status_summary"]["equivalent_content_deduplication"] = 201

            saved_label = f"Phase 10 saved failure {probe_id}"
            saved_payload = _saved_policy_payload(
                probe_id=probe_id,
                reform_id=first_legacy_id,
                reform_label=saved_label,
            )

        with _client("PHASE10_FAILURE_API_BASE_URL") as failure_client:
            failed_saved = failure_client.post("/us/user-policy", json=saved_payload)
            assert failed_saved.status_code == 503, failed_saved.text[:500]
            evidence["status_summary"]["saved_policy_controlled_failure"] = 503

        with _client("API_BASE_URL") as active_client:
            retried_saved = active_client.post("/us/user-policy", json=saved_payload)
            assert retried_saved.status_code == 200, retried_saved.text[:500]
            saved_policy_id = retried_saved.json()["result"]["id"]

            with v1_engine.connect() as connection:
                events = connection.execute(
                    text(
                        "SELECT source_revision, processed_at "
                        "FROM user_policy_mirror_events "
                        "WHERE country_id = 'us' "
                        "AND legacy_user_policy_id = :legacy_id "
                        "ORDER BY source_revision"
                    ),
                    {"legacy_id": saved_policy_id},
                ).all()
            assert [event.source_revision for event in events] == [1, 2]
            assert all(event.processed_at is not None for event in events)
            assert events[0].processed_at <= events[1].processed_at

            with v2_engine.connect() as connection:
                saved_mapping = connection.execute(
                    text(
                        "SELECT m.user_policy_id, m.last_applied_source_revision, "
                        "m.fingerprint_sha256, a.user_id, a.name, a.description "
                        "FROM legacy_user_policy_mappings m "
                        "JOIN user_policies a ON a.id = m.user_policy_id "
                        "WHERE m.country_id = 'us' "
                        "AND m.legacy_user_policy_id = :legacy_id"
                    ),
                    {"legacy_id": saved_policy_id},
                ).one()
                mapped_legacy_user_id = connection.scalar(
                    text(
                        "SELECT legacy_user_id FROM legacy_user_mappings "
                        "WHERE user_id = :user_id"
                    ),
                    {"user_id": saved_mapping.user_id},
                )
            assert saved_mapping.last_applied_source_revision == 2
            assert mapped_legacy_user_id == saved_payload["user_id"]
            assert saved_mapping.name == saved_label
            assert saved_mapping.description is None

            renamed_label = f"Phase 10 saved renamed {probe_id}"
            renamed = active_client.put(
                "/us/user-policy",
                json={"id": saved_policy_id, "reform_label": renamed_label},
            )
            assert renamed.status_code == 200, renamed.text[:500]
            with v2_engine.connect() as connection:
                renamed_mapping = connection.execute(
                    text(
                        "SELECT m.last_applied_source_revision, "
                        "m.fingerprint_sha256, a.name, a.description "
                        "FROM legacy_user_policy_mappings m "
                        "JOIN user_policies a ON a.id = m.user_policy_id "
                        "WHERE m.country_id = 'us' "
                        "AND m.legacy_user_policy_id = :legacy_id"
                    ),
                    {"legacy_id": saved_policy_id},
                ).one()
            assert renamed_mapping.last_applied_source_revision == 3
            assert renamed_mapping.name == renamed_label
            assert renamed_mapping.description is None

            v1_only_update = active_client.put(
                "/us/user-policy",
                json={"id": saved_policy_id, "number_of_provisions": 2},
            )
            assert v1_only_update.status_code == 200, v1_only_update.text[:500]
            with v2_engine.connect() as connection:
                v1_only_mapping = connection.execute(
                    text(
                        "SELECT m.last_applied_source_revision, "
                        "m.fingerprint_sha256, a.name, a.description "
                        "FROM legacy_user_policy_mappings m "
                        "JOIN user_policies a ON a.id = m.user_policy_id "
                        "WHERE m.country_id = 'us' "
                        "AND m.legacy_user_policy_id = :legacy_id"
                    ),
                    {"legacy_id": saved_policy_id},
                ).one()
            assert v1_only_mapping.last_applied_source_revision == 4
            assert (
                v1_only_mapping.fingerprint_sha256 != renamed_mapping.fingerprint_sha256
            )
            assert v1_only_mapping.name == renamed_label
            assert v1_only_mapping.description is None

            uk_parameters = active_client.get(
                "/v2/parameters",
                params={"country_id": "uk", "limit": 1},
            )
            assert uk_parameters.status_code == 200, uk_parameters.text[:500]
            uk_parameter_name = uk_parameters.json()["result"]["items"][0]["name"]
            uk_policy = active_client.post(
                "/uk/policy",
                json={
                    "label": f"Phase 10 UK {probe_id}",
                    "data": {
                        uk_parameter_name: {
                            "2026-01-01.2100-12-31": unique_value,
                        }
                    },
                },
            )
            assert uk_policy.status_code == 201, uk_policy.text[:500]
            uk_legacy_id = uk_policy.json()["result"]["policy_id"]
            with v2_engine.connect() as connection:
                uk_mapping_count = connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM legacy_policy_mappings "
                        "WHERE country_id = 'uk' AND legacy_policy_id = :legacy_id"
                    ),
                    {"legacy_id": uk_legacy_id},
                )
            assert uk_mapping_count == 1

        with _client("PHASE10_FAILURE_API_BASE_URL") as failure_client:
            for country_id in V1_ONLY_COUNTRIES:
                unsupported_policy = failure_client.post(
                    f"/{country_id}/policy",
                    json=_policy_payload(
                        f"Phase 10 {country_id} v1-only {probe_id}",
                        unique_value,
                    ),
                )
                assert unsupported_policy.status_code == 201, unsupported_policy.text[
                    :500
                ]
                unsupported_id = unsupported_policy.json()["result"]["policy_id"]
                _assert_v1_policy_identity(
                    failure_client.get(f"/{country_id}/policy/{unsupported_id}"),
                    unsupported_id,
                )
                unsupported_saved = failure_client.post(
                    f"/{country_id}/user-policy",
                    json={
                        **_saved_policy_payload(
                            probe_id=f"{country_id}-{probe_id}",
                            reform_id=unsupported_id,
                            reform_label=f"Phase 10 {country_id} saved {probe_id}",
                        ),
                        "geography": country_id,
                    },
                )
                assert unsupported_saved.status_code == 201, unsupported_saved.text[
                    :500
                ]
                unsupported_saved_id = unsupported_saved.json()["result"]["id"]
                with v2_engine.connect() as connection:
                    mapping_count = connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM legacy_policy_mappings "
                            "WHERE legacy_policy_id = :legacy_id"
                        ),
                        {"legacy_id": unsupported_id},
                    )
                assert mapping_count == 0
                with v1_engine.connect() as connection:
                    event_count = connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM user_policy_mirror_events "
                            "WHERE country_id = :country_id "
                            "AND legacy_user_policy_id = :legacy_id"
                        ),
                        {
                            "country_id": country_id,
                            "legacy_id": unsupported_saved_id,
                        },
                    )
                assert event_count == 0

        with v1_engine.connect() as connection:
            final_events = connection.execute(
                text(
                    "SELECT source_revision, processed_at "
                    "FROM user_policy_mirror_events "
                    "WHERE country_id = 'us' "
                    "AND legacy_user_policy_id = :legacy_id "
                    "ORDER BY source_revision"
                ),
                {"legacy_id": saved_policy_id},
            ).all()
        assert [event.source_revision for event in final_events] == [1, 2, 3, 4]
        assert all(event.processed_at is not None for event in final_events)

        evidence["status_summary"].update(
            {
                "saved_policy_retry": 200,
                "saved_policy_label_update": 200,
                "saved_policy_v1_only_update": 200,
                "uk_policy_mirror": 201,
                "v1_only_country_writes": 201,
            }
        )
        evidence["synthetic_ids"] = {
            "legacy_policy_id": first_legacy_id,
            "equivalent_legacy_policy_id": equivalent_legacy_id,
            "v2_policy_id": str(first_v2_id),
            "legacy_user_policy_id": saved_policy_id,
            "v2_user_policy_id": str(saved_mapping.user_policy_id),
        }
        evidence["counts_after_activation"] = _counts(v1_engine, v2_engine)
        _state_path().write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    finally:
        v1_engine.dispose()
        v2_engine.dispose()


def test_live_phase10_cloud_sql_only_rollback(integration_probe_id: str) -> None:
    """Verify rollback removes the v2 dependency without removing v2 state."""

    evidence = json.loads(_state_path().read_text(encoding="utf-8"))
    v1_engine = _v1_engine()
    v2_engine = _v2_engine()
    try:
        unique_value = 0.05 + (int(uuid4().hex[:6], 16) % 5000) / 1_000_000
        rollback_label = f"Phase 10 rollback {integration_probe_id}"
        with _client("API_BASE_URL") as rollback_client:
            rollback_created = rollback_client.post(
                "/us/policy",
                json=_policy_payload(rollback_label, unique_value),
            )
            assert rollback_created.status_code == 201, rollback_created.text[:500]
            rollback_legacy_id = rollback_created.json()["result"]["policy_id"]
            _assert_v1_policy_identity(
                rollback_client.get(f"/us/policy/{rollback_legacy_id}"),
                rollback_legacy_id,
            )

            with v2_engine.connect() as connection:
                rollback_mapping_count = connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM legacy_policy_mappings "
                        "WHERE country_id = 'us' AND legacy_policy_id = :legacy_id"
                    ),
                    {"legacy_id": rollback_legacy_id},
                )
            assert rollback_mapping_count == 0

            retained_v2_policy_id = evidence["synthetic_ids"]["v2_policy_id"]
            retained = rollback_client.get(
                f"/v2/policies/{retained_v2_policy_id}",
                params={"country_id": "us"},
            )
            assert retained.status_code == 200, retained.text[:500]
            assert retained.json()["result"]["item"]["id"] == retained_v2_policy_id

        evidence["rollback"] = {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "revision": _required_environment("PHASE10_CLOUD_SQL_REVISION"),
            "selectors": {
                "ROUTE_IMPL_POLICY": "fastapi_native",
                "DB_READ_POLICY": "cloud_sql",
                "DB_WRITE_POLICY": "cloud_sql",
            },
            "status_summary": {
                "v1_cloud_sql_only_policy_create": 201,
                "retained_v2_policy_read": 200,
            },
            "synthetic_legacy_policy_id": rollback_legacy_id,
        }
        evidence["counts_after_rollback"] = _counts(v1_engine, v2_engine)
        _state_path().write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    finally:
        v1_engine.dispose()
        v2_engine.dispose()
