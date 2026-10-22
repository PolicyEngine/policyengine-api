import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data.v1_models import Policy
from policyengine_api.services.policy_service import PolicyService, PolicySetResult
from tests.fixtures.services.policy_service import valid_policy_data

pytest_plugins = ["tests.fixtures.services.policy_service"]


@pytest.fixture
def service(orm_session_factory):
    return PolicyService(orm_session_factory)


@pytest.mark.usefixtures("existing_policy_record")
def test_get_policy_returns_mapped_entity(service):
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


@pytest.mark.usefixtures("existing_policy_record")
def test_get_policy_json_returns_python_object(service):
    result = service.get_policy_json("us", valid_policy_data["id"])

    assert result == {
        "gov.irs.income.bracket.rates.2": {"2024-01-01.2024-12-31": 0.2433}
    }


def test_set_policy_adds_mapped_entity(service, monkeypatch):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda _value: "new-hash",
    )

    result = service.set_policy(
        "US",
        "New policy",
        {"parameter": 1},
        prepare_for_mirroring=True,
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


def test_set_policy_builds_mirror_snapshot_from_refreshed_database_row(
    service,
    orm_session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda _value: "new-hash",
    )
    original_refresh = orm_session_factory.class_.refresh

    def refresh_with_database_normalization(session, policy, *args, **kwargs):
        original_refresh(session, policy, *args, **kwargs)
        policy.policy_json = {"parameter": 0.04094}

    monkeypatch.setattr(
        orm_session_factory.class_,
        "refresh",
        refresh_with_database_normalization,
    )

    result = service.set_policy(
        "us",
        "Normalized policy",
        {"parameter": 0.040940000000000004},
        prepare_for_mirroring=True,
    )

    assert result.snapshot is not None
    assert result.snapshot.policy_json == {"parameter": 0.04094}


@pytest.mark.usefixtures("existing_policy_record")
def test_set_policy_returns_existing_mapped_entity(
    service,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda _value: valid_policy_data["policy_hash"],
    )

    result = service.set_policy(
        "us",
        None,
        {},
        prepare_for_mirroring=True,
    )
    policy_id, message, exists = result

    assert policy_id == valid_policy_data["id"]
    assert message == "Policy already exists"
    assert exists is True
    assert result.snapshot.legacy_policy_id == valid_policy_data["id"]
    assert result.snapshot.source_policy_hash == valid_policy_data["policy_hash"]


def test_set_policy_does_not_build_v2_snapshot_unless_requested(
    service,
    monkeypatch,
):
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.hash_object",
        lambda _value: "new-hash",
    )
    monkeypatch.setattr(
        service._sessions.class_,
        "refresh",
        lambda *_args, **_kwargs: pytest.fail("cloud_sql-only writes must not refresh"),
    )

    result = service.set_policy(
        "ca",
        "Canadian policy",
        {"parameter": 1},
    )

    assert result.snapshot is None
    assert service.get_policy("ca", result.policy_id) is not None


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
        lambda _value: "new-hash",
    )
    monkeypatch.setattr(
        orm_session_factory.class_,
        "flush",
        lambda _self: (_ for _ in ()).throw(SQLAlchemyError("insert failed")),
    )

    with pytest.raises(SQLAlchemyError, match="insert failed"):
        service.set_policy("us", "Policy", {})


def test_mirror_snapshot_read_failure_rolls_back_new_v1_policy(
    service, orm_session_factory, monkeypatch
):
    with monkeypatch.context() as failing_read:
        failing_read.setattr(
            orm_session_factory.class_,
            "refresh",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                SQLAlchemyError("snapshot read failed")
            ),
        )
        with pytest.raises(SQLAlchemyError, match="snapshot read failed"):
            service.set_policy("us", "Failed snapshot", {}, prepare_for_mirroring=True)

    with orm_session_factory() as session:
        stored_labels = session.scalars(
            select(Policy.label).where(Policy.label == "Failed snapshot")
        ).all()
    assert stored_labels == []
    retry = service.set_policy("us", "Failed snapshot", {}, prepare_for_mirroring=True)
    assert retry.is_existing_policy is False
    assert retry.snapshot == service.get_policy_snapshot("us", retry.policy_id)
