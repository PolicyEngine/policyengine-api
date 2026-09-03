"""Write/read lifecycle checks for deployed native v2 policy resources."""

from __future__ import annotations

import os
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def _v2_database_url() -> str:
    value = os.environ.get("V2_MIGRATION_DATABASE_URL")
    if not value:
        raise RuntimeError(
            "V2_MIGRATION_DATABASE_URL is required for the live v2 probe"
        )
    return value


def _one_catalog_item(api_client, resource: str, *, country_id: str) -> dict:
    response = api_client.get(
        f"/v2/{resource}",
        params={"country_id": country_id, "limit": 1},
    )
    assert response.status_code == 200, response.text[:500]
    items = response.json()["result"]["items"]
    assert len(items) == 1
    return items[0]


def test_live_native_policy_and_user_policy_lifecycle(
    api_client,
    integration_probe_id: str,
) -> None:
    """Exercise every Phase 10 native route against the staging database."""

    country_id = "us"
    model = _one_catalog_item(
        api_client,
        "tax-benefit-models",
        country_id=country_id,
    )
    parameter = _one_catalog_item(
        api_client,
        "parameters",
        country_id=country_id,
    )
    user_id = uuid4()
    engine = create_engine(_v2_database_url(), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, primary_country) VALUES (:id, :country_id)"
                ),
                {"id": user_id, "country_id": country_id},
            )
            existing_policy_count = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM policies "
                    "WHERE country_id = :country_id "
                    "AND tax_benefit_model_id = :model_id"
                ),
                {"country_id": country_id, "model_id": model["id"]},
            )

        policy_body = {
            "country_id": country_id,
            "tax_benefit_model_id": model["id"],
            "parameter_values": [
                {
                    "parameter_id": parameter["id"],
                    "value": f"phase10-native-{integration_probe_id}",
                    "start_date": "2026-01-01T00:00:00Z",
                }
            ],
        }
        created = api_client.post(
            "/v2/policies",
            params={"country_id": country_id},
            json=policy_body,
        )
        assert created.status_code == 201, created.text[:500]
        created_item = created.json()["result"]["item"]
        policy_id = created_item["id"]
        assert created_item["country_id"] == country_id
        assert created_item["tax_benefit_model_id"] == model["id"]
        assert created_item["parameter_values"][0]["parameter_id"] == parameter["id"]
        assert (
            created_item["parameter_values"][0]["parameter_name"] == parameter["name"]
        )
        assert created_item["created_at"]
        assert created_item["updated_at"]

        repeated = api_client.post(
            "/v2/policies",
            params={"country_id": country_id},
            json=policy_body,
        )
        assert repeated.status_code == 200, repeated.text[:500]
        assert repeated.json()["result"]["item"]["id"] == policy_id

        detail = api_client.get(
            f"/v2/policies/{policy_id}",
            params={"country_id": country_id},
        )
        assert detail.status_code == 200, detail.text[:500]
        assert detail.json()["result"]["item"] == created_item

        collection = api_client.get(
            "/v2/policies",
            params={
                "country_id": country_id,
                "tax_benefit_model_id": model["id"],
                "offset": existing_policy_count,
                "limit": 1,
            },
        )
        assert collection.status_code == 200, collection.text[:500]
        assert policy_id in {
            item["id"] for item in collection.json()["result"]["items"]
        }

        association_body = {
            "country_id": country_id,
            "user_id": str(user_id),
            "policy_id": policy_id,
            "name": f"Phase 10 native {integration_probe_id}",
            "description": "Synthetic staging lifecycle record",
        }
        association = api_client.post(
            "/v2/user-policies",
            params={"country_id": country_id},
            json=association_body,
        )
        assert association.status_code == 201, association.text[:500]
        association_item = association.json()["result"]["item"]
        association_id = association_item["id"]

        association_detail = api_client.get(
            f"/v2/user-policies/{association_id}",
            params={"country_id": country_id},
        )
        assert association_detail.status_code == 200, association_detail.text[:500]
        assert association_detail.json()["result"]["item"] == association_item

        association_collection = api_client.get(
            "/v2/user-policies",
            params={
                "country_id": country_id,
                "user_id": str(user_id),
                "policy_id": policy_id,
            },
        )
        assert association_collection.status_code == 200
        assert [
            item["id"] for item in association_collection.json()["result"]["items"]
        ] == [association_id]

        updated_name = f"Phase 10 renamed {integration_probe_id}"
        patched = api_client.patch(
            f"/v2/user-policies/{association_id}",
            params={"country_id": country_id},
            json={"name": updated_name},
        )
        assert patched.status_code == 200, patched.text[:500]
        patched_item = patched.json()["result"]["item"]
        assert patched_item["name"] == updated_name
        assert patched_item["description"] == association_body["description"]

        deleted = api_client.delete(
            f"/v2/user-policies/{association_id}",
            params={"country_id": country_id},
        )
        assert deleted.status_code == 204, deleted.text[:500]
        absent = api_client.get(
            f"/v2/user-policies/{association_id}",
            params={"country_id": country_id},
        )
        assert absent.status_code == 404, absent.text[:500]
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM users WHERE id = :id"),
                {"id": user_id},
            )
        engine.dispose()
