"""Service tests for native v2 user-policy associations."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine, select

from policyengine_api.data.v2.models import (
    LegacyUserPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    UserPolicy,
    V2_METADATA,
)
from policyengine_api.data.v2.user_policies.persistence import (
    AssociationCountryConflictError,
    AssociationPolicyNotFoundError,
)
from policyengine_api.data.v2.user_policies.query import UserPolicyNotFoundError
from policyengine_api.data.v2.user_policies.schemas import (
    UserPolicyCreateCommand,
    UserPolicyPatchCommand,
)
from policyengine_api.data.v2.user_policies.service import V2UserPolicyService


@pytest.fixture
def association_store():
    engine = create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    V2_METADATA.create_all(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    with sessions.begin() as session:
        model = TaxBenefitModel(name="policyengine-us")
        version = TaxBenefitModelVersion(
            model=model,
            version="5.2.0",
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        parameter = Parameter(
            name="gov.example.rate",
            tax_benefit_model_version=version,
        )
        policy = Policy(
            country_id="us",
            tax_benefit_model=model,
            tax_benefit_model_version=version,
            canonicalization_version=1,
            content_hash="a" * 64,
        )
        value = ParameterValue(
            parameter=parameter,
            policy=policy,
            value_json=0.2,
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        session.add(value)
        session.flush()
        identity = (policy.id, value.id)

    yield V2UserPolicyService(sessions), sessions, identity
    engine.dispose()


def _command(policy_id, **changes) -> UserPolicyCreateCommand:
    values = {
        "country_id": "us",
        "user_id": "auth0|caller",
        "policy_id": policy_id,
        "name": "Saved reform",
        "description": "Personal note",
    }
    values.update(changes)
    return UserPolicyCreateCommand.model_validate(values)


def test_create_allows_distinct_duplicate_links_and_unverified_user(
    association_store,
) -> None:
    service, sessions, (policy_id, _value_id) = association_store

    first = service.create_user_policy(_command(policy_id))
    second = service.create_user_policy(_command(policy_id, name="Second save"))

    assert first.id != second.id
    assert first.user_id == "auth0|caller"
    assert second.policy_id == policy_id
    with sessions() as session:
        assert len(session.exec(select(UserPolicy)).all()) == 2


def test_create_rejects_missing_policy_and_country_conflict(
    association_store,
) -> None:
    service, _sessions, (policy_id, _value_id) = association_store

    with pytest.raises(AssociationPolicyNotFoundError):
        service.create_user_policy(_command("00000000-0000-0000-0000-000000000099"))
    with pytest.raises(AssociationCountryConflictError):
        service.create_user_policy(_command(policy_id, country_id="uk"))


def test_detail_list_filter_and_pagination_are_country_scoped(
    association_store,
) -> None:
    service, _sessions, (policy_id, _value_id) = association_store
    first = service.create_user_policy(_command(policy_id, name="First"))
    service.create_user_policy(_command(policy_id, name="Second"))
    service.create_user_policy(
        _command(policy_id, user_id="another-user", name="Other")
    )

    detail = service.get_user_policy(
        country_id="us",
        association_id=first.id,
    )
    page = service.list_user_policies(
        country_id="us",
        user_id="auth0|caller",
        policy_id=policy_id,
        limit=1,
    )
    second_page = service.list_user_policies(
        country_id="us",
        user_id="auth0|caller",
        offset=1,
        limit=1,
    )

    assert detail.id == first.id
    assert [item.name for item in page.items] == ["First"]
    assert page.has_more is True
    assert [item.name for item in second_page.items] == ["Second"]
    with pytest.raises(UserPolicyNotFoundError):
        service.get_user_policy(country_id="uk", association_id=first.id)


def test_patch_changes_only_supplied_fields_and_supports_null_clearing(
    association_store,
) -> None:
    service, _sessions, (policy_id, _value_id) = association_store
    created = service.create_user_policy(_command(policy_id))

    renamed = service.patch_user_policy(
        country_id="us",
        association_id=created.id,
        command=UserPolicyPatchCommand(name="Renamed"),
    )
    cleared = service.patch_user_policy(
        country_id="us",
        association_id=created.id,
        command=UserPolicyPatchCommand(description=None),
    )

    assert renamed.name == "Renamed"
    assert renamed.description == "Personal note"
    assert cleared.name == "Renamed"
    assert cleared.description is None
    assert cleared.updated_at >= created.updated_at
    assert (cleared.country_id, cleared.user_id, cleared.policy_id) == (
        "us",
        "auth0|caller",
        policy_id,
    )


def test_delete_removes_mapping_but_preserves_policy_and_parameter_value(
    association_store,
) -> None:
    service, sessions, (policy_id, value_id) = association_store
    created = service.create_user_policy(_command(policy_id))
    with sessions.begin() as session:
        mapping = LegacyUserPolicyMapping(
            country_id="us",
            legacy_user_policy_id=42,
            user_policy_id=created.id,
            fingerprint_version=1,
            fingerprint_sha256="b" * 64,
        )
        session.add(mapping)
        session.flush()
        mapping_id = mapping.id

    service.delete_user_policy(country_id="us", association_id=created.id)

    with sessions() as session:
        assert session.get(UserPolicy, created.id) is None
        assert session.get(LegacyUserPolicyMapping, mapping_id) is None
        assert session.get(Policy, policy_id) is not None
        assert session.get(ParameterValue, value_id) is not None


def test_patch_command_rejects_empty_and_immutable_fields() -> None:
    with pytest.raises(ValueError):
        UserPolicyPatchCommand()
    with pytest.raises(ValueError):
        UserPolicyPatchCommand.model_validate(
            {"policy_id": "00000000-0000-0000-0000-000000000001"}
        )
