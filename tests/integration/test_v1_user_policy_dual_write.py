"""Cross-database tests for immediate v1 saved-policy association mirroring."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.constants import POLICYENGINE_VERSION
from policyengine_api.data.v1_models import UserPolicyMirrorEvent
from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.models import (
    LegacyPolicyMapping,
    LegacyUserMapping,
    LegacyUserPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    User,
    UserPolicy,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.services.v2.user_policy_service import V2UserPolicyService
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.user_policy_mirroring import (
    UserPolicyMirrorUnavailableError,
    mirror_pending_user_policy_events_after_commit,
    mirror_user_policy_after_commit,
)
from policyengine_api.services.user_policy_service import UserPolicyService


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: database_url,
            V2_ALEMBIC_DISPOSABLE_TEST: os.environ.get(
                V2_ALEMBIC_DISPOSABLE_TEST,
                "",
            ),
        }
    )
    if not settings.disposable_test:
        pytest.fail("saved-policy cross-database tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


def _v1_services():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE policy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_id VARCHAR(3) NOT NULL,
                label VARCHAR(255),
                api_version VARCHAR(10) NOT NULL,
                policy_json JSON NOT NULL,
                policy_hash VARCHAR(255) NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE user_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_id VARCHAR(3) NOT NULL,
                reform_id INTEGER NOT NULL,
                reform_label VARCHAR(255),
                baseline_id INTEGER NOT NULL,
                baseline_label VARCHAR(255),
                user_id VARCHAR(255) NOT NULL,
                year VARCHAR(32) NOT NULL,
                geography VARCHAR(255) NOT NULL,
                dataset VARCHAR(255),
                number_of_provisions INTEGER NOT NULL,
                api_version VARCHAR(32) NOT NULL,
                added_date BIGINT NOT NULL,
                updated_date BIGINT NOT NULL,
                budgetary_impact VARCHAR(255),
                type VARCHAR(255),
                mirror_revision BIGINT NOT NULL DEFAULT 0
            )
            """
        )
        UserPolicyMirrorEvent.__table__.create(connection)
    sessions = sessionmaker(engine, expire_on_commit=False)
    return engine, PolicyService(sessions), UserPolicyService(sessions), sessions


def _seed_catalog(sessions):
    with sessions.begin() as session:
        model = TaxBenefitModel(name="policyengine-us")
        version = TaxBenefitModelVersion(
            model=model,
            version=POLICYENGINE_VERSION,
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        parameter = Parameter(
            name="gov.phase10.cross_database_saved_rate",
            tax_benefit_model_version=version,
        )
        session.add(parameter)
        session.flush()
        return model.id, parameter.name


def _saved_values(reform_id: int, **changes):
    values = {
        "country_id": "us",
        "reform_id": reform_id,
        "reform_label": "Reform",
        "baseline_id": 0,
        "baseline_label": "Current law",
        "user_id": "auth0|cross-database",
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
    values.update(changes)
    return values


def _cleanup(engine, model_id) -> None:
    if model_id is None:
        return
    with engine.begin() as connection:
        user_ids = (
            connection.execute(
                select(LegacyUserMapping.user_id).where(
                    LegacyUserMapping.legacy_user_id == "auth0|cross-database"
                )
            )
            .scalars()
            .all()
        )
        connection.execute(
            delete(LegacyUserMapping).where(
                LegacyUserMapping.legacy_user_id == "auth0|cross-database"
            )
        )
        policy_ids = select(Policy.id).where(Policy.tax_benefit_model_id == model_id)
        association_ids = select(UserPolicy.id).where(
            UserPolicy.policy_id.in_(policy_ids)
        )
        connection.execute(
            delete(LegacyUserPolicyMapping).where(
                LegacyUserPolicyMapping.user_policy_id.in_(association_ids)
            )
        )
        connection.execute(
            delete(UserPolicy).where(UserPolicy.policy_id.in_(policy_ids))
        )
        if user_ids:
            connection.execute(delete(User).where(User.id.in_(user_ids)))
        connection.execute(
            delete(LegacyPolicyMapping).where(
                LegacyPolicyMapping.policy_id.in_(policy_ids)
            )
        )
        connection.execute(
            delete(ParameterValue).where(ParameterValue.policy_id.in_(policy_ids))
        )
        connection.execute(
            delete(Policy).where(Policy.tax_benefit_model_id == model_id)
        )
        version_ids = select(TaxBenefitModelVersion.id).where(
            TaxBenefitModelVersion.model_id == model_id
        )
        connection.execute(
            delete(Parameter).where(
                Parameter.tax_benefit_model_version_id.in_(version_ids)
            )
        )
        connection.execute(
            delete(TaxBenefitModelVersion).where(
                TaxBenefitModelVersion.model_id == model_id
            )
        )
        connection.execute(
            delete(TaxBenefitModel).where(TaxBenefitModel.id == model_id)
        )


def test_create_update_and_v1_only_change_mirror_one_association() -> None:
    v2_engine = create_engine(_disposable_url())
    v2_sessions = sessionmaker(v2_engine, class_=Session, expire_on_commit=False)
    v1_engine, policy_service, saved_service, _v1_sessions = _v1_services()
    model_id = None
    try:
        model_id, parameter_name = _seed_catalog(v2_sessions)
        reform = policy_service.set_policy(
            "us",
            "Legacy reform label",
            {parameter_name: {"2026": 0.2}},
        )
        created = saved_service.create_or_get_user_policy(
            _saved_values(reform.policy_id),
            record_mirror_event=True,
        )
        mirror_service = V2UserPolicyService(v2_sessions)
        first = mirror_pending_user_policy_events_after_commit(
            "us",
            created.user_policy.id,
            through_revision=created.mirror_revision,
            event_service=saved_service,
            reform_snapshot_loader=policy_service.get_policy_snapshot,
            mirror_factory=lambda: mirror_service,
        )

        renamed = saved_service.update_user_policy(
            "us",
            created.user_policy.id,
            {"reform_label": "Renamed", "updated_date": 3},
            record_mirror_event=True,
        )
        rename_result = mirror_pending_user_policy_events_after_commit(
            "us",
            created.user_policy.id,
            through_revision=renamed.mirror_revision,
            event_service=saved_service,
            reform_snapshot_loader=policy_service.get_policy_snapshot,
            mirror_factory=lambda: mirror_service,
        )
        v1_only = saved_service.update_user_policy(
            "us",
            created.user_policy.id,
            {"year": "2027", "updated_date": 4},
            record_mirror_event=True,
        )
        v1_only_result = mirror_pending_user_policy_events_after_commit(
            "us",
            created.user_policy.id,
            through_revision=v1_only.mirror_revision,
            event_service=saved_service,
            reform_snapshot_loader=policy_service.get_policy_snapshot,
            mirror_factory=lambda: mirror_service,
        )

        assert first.association_id == rename_result.association_id
        assert first.association_id == v1_only_result.association_id
        assert rename_result.association_updated is True
        assert v1_only_result.association_updated is False
        with v2_sessions() as session:
            association = session.get(UserPolicy, first.association_id)
            assert association.name == "Renamed"
            assert association.description is None
            user_mapping = session.scalar(select(LegacyUserMapping))
            assert association.user_id == user_mapping.user_id
            assert session.get(User, user_mapping.user_id).primary_country == "us"
            assert (
                session.scalar(
                    select(func.count()).select_from(LegacyUserPolicyMapping)
                )
                == 1
            )
            mapping = session.scalar(select(LegacyUserPolicyMapping))
            assert mapping.last_applied_source_revision == 3
    finally:
        _cleanup(v2_engine, model_id)
        v1_engine.dispose()
        v2_engine.dispose()


def test_failure_after_cloud_commit_and_identical_create_retry_are_idempotent() -> None:
    v2_engine = create_engine(_disposable_url())
    v2_sessions = sessionmaker(v2_engine, class_=Session, expire_on_commit=False)
    v1_engine, policy_service, saved_service, v1_sessions = _v1_services()
    model_id = None
    parameter_name = "gov.phase10.cross_database_saved_rate"
    try:
        reform = policy_service.set_policy(
            "us",
            "Legacy reform label",
            {parameter_name: {"2026": 0.2}},
        )
        created = saved_service.create_or_get_user_policy(
            _saved_values(reform.policy_id),
            record_mirror_event=True,
        )
        mirror_service = V2UserPolicyService(v2_sessions)

        with pytest.raises(UserPolicyMirrorUnavailableError):
            mirror_pending_user_policy_events_after_commit(
                "us",
                created.user_policy.id,
                through_revision=created.mirror_revision,
                event_service=saved_service,
                reform_snapshot_loader=policy_service.get_policy_snapshot,
                mirror_factory=lambda: mirror_service,
            )

        with v1_sessions() as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(created.user_policy.__class__)
                )
                == 1
            )
            event = session.scalar(select(UserPolicyMirrorEvent))
            assert event.processed_at is None
        with v2_sessions() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 0
            assert (
                session.scalar(select(func.count()).select_from(LegacyUserMapping)) == 0
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(LegacyUserPolicyMapping)
                )
                == 0
            )

        model_id, _parameter_name = _seed_catalog(v2_sessions)
        retry = saved_service.create_or_get_user_policy(
            _saved_values(reform.policy_id, number_of_provisions=99),
            record_mirror_event=True,
        )
        result = mirror_pending_user_policy_events_after_commit(
            "us",
            retry.user_policy.id,
            through_revision=retry.mirror_revision,
            event_service=saved_service,
            reform_snapshot_loader=policy_service.get_policy_snapshot,
            mirror_factory=lambda: mirror_service,
        )

        assert retry.created is False
        assert retry.user_policy.id == created.user_policy.id
        assert result.association_created is False
        with v1_sessions() as session:
            events = session.scalars(select(UserPolicyMirrorEvent)).all()
            assert [event.source_revision for event in events] == [1, 2]
            assert all(event.processed_at is not None for event in events)
        with v2_sessions() as session:
            mapping = session.scalar(select(LegacyUserPolicyMapping))
            assert mapping.last_applied_source_revision == 2
            assert session.scalar(select(func.count()).select_from(User)) == 1
            assert (
                session.scalar(select(func.count()).select_from(LegacyUserMapping)) == 1
            )
    finally:
        _cleanup(v2_engine, model_id)
        v1_engine.dispose()
        v2_engine.dispose()


def test_destination_commit_replays_when_source_processing_marker_is_missing() -> None:
    v2_engine = create_engine(_disposable_url())
    v2_sessions = sessionmaker(v2_engine, class_=Session, expire_on_commit=False)
    v1_engine, policy_service, saved_service, v1_sessions = _v1_services()
    model_id = None
    try:
        model_id, parameter_name = _seed_catalog(v2_sessions)
        reform = policy_service.set_policy(
            "us",
            "Legacy reform label",
            {parameter_name: {"2026": 0.2}},
        )
        created = saved_service.create_or_get_user_policy(
            _saved_values(reform.policy_id),
            record_mirror_event=True,
        )
        mirror_service = V2UserPolicyService(v2_sessions)

        committed = mirror_user_policy_after_commit(
            created.snapshot,
            reform.snapshot,
            source_revision=created.mirror_revision,
            mirror_factory=lambda: mirror_service,
        )
        with v1_sessions() as session:
            event = session.scalar(select(UserPolicyMirrorEvent))
            assert event.processed_at is None

        replayed = mirror_pending_user_policy_events_after_commit(
            "us",
            created.user_policy.id,
            through_revision=created.mirror_revision,
            event_service=saved_service,
            reform_snapshot_loader=policy_service.get_policy_snapshot,
            mirror_factory=lambda: mirror_service,
        )

        assert replayed.association_id == committed.association_id
        assert replayed.association_created is False
        with v1_sessions() as session:
            event = session.scalar(select(UserPolicyMirrorEvent))
            assert event.processed_at is not None
        with v2_sessions() as session:
            assert session.scalar(select(func.count()).select_from(UserPolicy)) == 1
            assert session.scalar(select(func.count()).select_from(User)) == 1
            assert (
                session.scalar(select(func.count()).select_from(LegacyUserMapping)) == 1
            )
            mapping = session.scalar(select(LegacyUserPolicyMapping))
            assert mapping.last_applied_source_revision == 1
    finally:
        _cleanup(v2_engine, model_id)
        v1_engine.dispose()
        v2_engine.dispose()
