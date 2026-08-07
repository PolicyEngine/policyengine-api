import pytest
from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.v1_models import Policy
from policyengine_api.services.policy_service import PolicyService
from tests.fixtures.services.policy_service import valid_policy_data


pytest_plugins = ["tests.fixtures.services.policy_service"]


service = PolicyService()


def test_get_policy_returns_mapped_entity(orm_session, existing_policy_record):
    policy = service.get_policy(
        orm_session,
        valid_policy_data["country_id"],
        valid_policy_data["id"],
    )

    assert isinstance(policy, Policy)
    assert policy.id == valid_policy_data["id"]
    assert policy.policy_json == {
        "gov.irs.income.bracket.rates.2": {"2024-01-01.2024-12-31": 0.2433}
    }


def test_get_policy_returns_none_for_missing_entity(orm_session):
    assert service.get_policy(orm_session, "us", 999) is None


@pytest.mark.parametrize("policy_id", ["invalid", -1])
def test_get_policy_rejects_invalid_id(orm_session, policy_id):
    with pytest.raises(Exception, match="Invalid policy ID"):
        service.get_policy(orm_session, "us", policy_id)


@pytest.mark.parametrize("country_id", ["", None])
def test_get_policy_rejects_empty_country(orm_session, country_id):
    with pytest.raises(ValueError, match="country_id cannot be empty or None"):
        service.get_policy(orm_session, country_id, 1)


def test_get_policy_json_returns_python_object(orm_session, existing_policy_record):
    result = service.get_policy_json(orm_session, "us", valid_policy_data["id"])

    assert result == {
        "gov.irs.income.bracket.rates.2": {"2024-01-01.2024-12-31": 0.2433}
    }


def test_set_policy_adds_mapped_entity(orm_session, monkeypatch):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda value: "new-hash",
    )

    policy_id, message, exists = service.set_policy(
        orm_session,
        "US",
        "New policy",
        {"parameter": 1},
    )

    policy = service.get_policy(orm_session, "us", policy_id)
    assert policy.policy_json == {"parameter": 1}
    assert policy.api_version == COUNTRY_PACKAGE_VERSIONS["us"]
    assert message == "Policy created"
    assert exists is False


def test_set_policy_returns_existing_mapped_entity(
    orm_session,
    existing_policy_record,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda value: valid_policy_data["policy_hash"],
    )

    policy_id, message, exists = service.set_policy(
        orm_session,
        "us",
        None,
        {},
    )

    assert policy_id == valid_policy_data["id"]
    assert message == "Policy already exists"
    assert exists is True


def test_set_policy_rejects_invalid_country(orm_session):
    with pytest.raises(ValueError, match="Invalid country_id: xx"):
        service.set_policy(orm_session, "xx", "Policy", {})


def test_set_policy_propagates_flush_failure(orm_session, monkeypatch):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda value: "new-hash",
    )
    monkeypatch.setattr(
        orm_session,
        "flush",
        lambda: (_ for _ in ()).throw(SQLAlchemyError("insert failed")),
    )

    with pytest.raises(SQLAlchemyError, match="insert failed"):
        service.set_policy(orm_session, "us", "Policy", {})
