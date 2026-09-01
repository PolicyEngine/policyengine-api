import pytest
from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.v1_models import Policy
from policyengine_api.services.policy_service import PolicyService, PolicySetResult
from tests.fixtures.services.policy_service import valid_policy_data


pytest_plugins = ["tests.fixtures.services.policy_service"]


@pytest.fixture
def service(orm_session_factory):
    return PolicyService(orm_session_factory)


def test_get_policy_returns_mapped_entity(service, existing_policy_record):
    policy = service.get_policy(
        valid_policy_data["country_id"],
        valid_policy_data["id"],
    )

    assert isinstance(policy, Policy)
    assert policy.id == valid_policy_data["id"]
    assert policy.policy_json == {
        "gov.irs.income.bracket.rates.2": {"2024-01-01.2024-12-31": 0.2433}
    }


def test_get_policy_returns_none_for_missing_entity(service):
    assert service.get_policy("us", 999) is None


@pytest.mark.parametrize("policy_id", ["invalid", -1])
def test_get_policy_rejects_invalid_id(service, policy_id):
    with pytest.raises(Exception, match="Invalid policy ID"):
        service.get_policy("us", policy_id)


@pytest.mark.parametrize("country_id", ["", None])
def test_get_policy_rejects_empty_country(service, country_id):
    with pytest.raises(ValueError, match="country_id cannot be empty or None"):
        service.get_policy(country_id, 1)


def test_get_policy_json_returns_python_object(service, existing_policy_record):
    result = service.get_policy_json("us", valid_policy_data["id"])

    assert result == {
        "gov.irs.income.bracket.rates.2": {"2024-01-01.2024-12-31": 0.2433}
    }


def test_search_policies_filters_and_deduplicates(service, orm_session_factory):
    with orm_session_factory.begin() as session:
        session.add_all(
            [
                Policy(
                    id=31,
                    country_id="us",
                    label="Tax reform",
                    api_version="1",
                    policy_json={},
                    policy_hash="same-hash",
                ),
                Policy(
                    id=32,
                    country_id="us",
                    label="Tax reform",
                    api_version="1",
                    policy_json={"different": True},
                    policy_hash="same-hash",
                ),
                Policy(
                    id=33,
                    country_id="us",
                    label="Benefit reform",
                    api_version="1",
                    policy_json={},
                    policy_hash="other-hash",
                ),
            ]
        )

    all_results = service.search_policies("us", "Tax", unique_only=False)
    unique_results = service.search_policies("us", "Tax", unique_only=True)
    escaped_wildcard_results = service.search_policies("us", "Tax%", unique_only=False)

    assert len(all_results) == 2
    assert len(unique_results) == 1
    assert unique_results[0].label == "Tax reform"
    assert escaped_wildcard_results == []


def test_set_policy_adds_mapped_entity(service, monkeypatch):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda value: "new-hash",
    )

    result = service.set_policy(
        "US",
        "New policy",
        {"parameter": 1},
    )
    policy_id, message, exists = result

    policy = service.get_policy("us", policy_id)
    assert policy.policy_json == {"parameter": 1}
    assert policy.api_version == COUNTRY_PACKAGE_VERSIONS["us"]
    assert message == "Policy created"
    assert exists is False
    assert isinstance(result, PolicySetResult)
    assert result.snapshot.model_dump() == {
        "country_id": "us",
        "legacy_policy_id": policy_id,
        "label": "New policy",
        "api_version": COUNTRY_PACKAGE_VERSIONS["us"],
        "policy_json": {"parameter": 1},
        "source_policy_hash": "new-hash",
    }


def test_set_policy_returns_existing_mapped_entity(
    service,
    existing_policy_record,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda value: valid_policy_data["policy_hash"],
    )

    result = service.set_policy(
        "us",
        None,
        {},
    )
    policy_id, message, exists = result

    assert policy_id == valid_policy_data["id"]
    assert message == "Policy already exists"
    assert exists is True
    assert result.snapshot.legacy_policy_id == valid_policy_data["id"]
    assert result.snapshot.source_policy_hash == valid_policy_data["policy_hash"]


def test_set_policy_rejects_invalid_country(service):
    with pytest.raises(ValueError, match="Invalid country_id: xx"):
        service.set_policy("xx", "Policy", {})


def test_set_policy_propagates_flush_failure(
    service,
    orm_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda value: "new-hash",
    )
    monkeypatch.setattr(
        orm_session_factory.class_,
        "flush",
        lambda self: (_ for _ in ()).throw(SQLAlchemyError("insert failed")),
    )

    with pytest.raises(SQLAlchemyError, match="insert failed"):
        service.set_policy("us", "Policy", {})
