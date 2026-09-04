"""Cross-database transaction tests for immediate v1 policy mirroring."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.constants import POLICYENGINE_VERSION
from policyengine_api.data.v1_models import Policy as V1Policy
from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.models import (
    LegacyPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import (
    V2PolicyService,
    mirror_legacy_policy_in_session,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.services.policy_mirroring import (
    PolicyMirrorUnavailableError,
    mirror_policy_after_commit,
)
from policyengine_api.services.policy_service import PolicyService


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
        pytest.fail("dual-write tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


def _v1_service():
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
    sessions = sessionmaker(engine, expire_on_commit=False)
    return engine, PolicyService(sessions)


def _seed_catalog(v2_sessions) -> tuple[object, str]:
    with v2_sessions.begin() as session:
        model = TaxBenefitModel(name="policyengine-us")
        version = TaxBenefitModelVersion(
            model=model,
            version=POLICYENGINE_VERSION,
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        parameter = Parameter(
            name="gov.phase10.cross_database_rate",
            tax_benefit_model_version=version,
        )
        session.add(parameter)
        session.flush()
        return model.id, parameter.name


def _cleanup_v2(v2_engine, model_id) -> None:
    if model_id is None:
        return
    with v2_engine.begin() as connection:
        policy_ids = select(Policy.id).where(Policy.tax_benefit_model_id == model_id)
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


def _create_v1(service: PolicyService, parameter_name: str):
    return service.set_policy(
        "us",
        "Cross-database policy",
        {parameter_name: {"2026": 0.2}},
        prepare_for_mirroring=True,
    )


def test_both_commits_and_interrupted_response_retry_resolve_one_mapping() -> None:
    v2_engine = create_engine(_disposable_url())
    v2_sessions = sessionmaker(v2_engine, class_=Session, expire_on_commit=False)
    v1_engine, v1_service = _v1_service()
    model_id = None
    try:
        model_id, parameter_name = _seed_catalog(v2_sessions)
        mirror_service = V2PolicyService(PolicyDatabaseSession(v2_sessions))
        creation = _create_v1(v1_service, parameter_name)
        first = mirror_policy_after_commit(
            creation.snapshot,
            mirror_factory=lambda: mirror_service,
        )

        # Simulate losing the HTTP response after both commits by repeating the
        # exact create and mirror operations.
        retry_creation = _create_v1(v1_service, parameter_name)
        retry = mirror_policy_after_commit(
            retry_creation.snapshot,
            mirror_factory=lambda: mirror_service,
        )

        assert creation.is_existing_policy is False
        assert retry_creation.is_existing_policy is True
        assert retry.policy_id == first.policy_id
        with v2_sessions() as session:
            assert (
                session.scalar(select(func.count()).select_from(LegacyPolicyMapping))
                == 1
            )
            assert session.scalar(select(func.count()).select_from(Policy)) == 1
        assert v1_service.get_policy("us", creation.policy_id) is not None
    finally:
        _cleanup_v2(v2_engine, model_id)
        v1_engine.dispose()
        v2_engine.dispose()


def test_catalog_failure_leaves_cloud_sql_committed_and_retry_completes() -> None:
    v2_engine = create_engine(_disposable_url())
    v2_sessions = sessionmaker(v2_engine, class_=Session, expire_on_commit=False)
    v1_engine, v1_service = _v1_service()
    model_id = None
    parameter_name = "gov.phase10.cross_database_rate"
    try:
        creation = _create_v1(v1_service, parameter_name)
        mirror_service = V2PolicyService(PolicyDatabaseSession(v2_sessions))

        with pytest.raises(PolicyMirrorUnavailableError):
            mirror_policy_after_commit(
                creation.snapshot,
                mirror_factory=lambda: mirror_service,
            )

        assert v1_service.get_policy("us", creation.policy_id) is not None
        with v2_sessions() as session:
            assert (
                session.scalar(select(func.count()).select_from(LegacyPolicyMapping))
                == 0
            )

        model_id, _parameter_name = _seed_catalog(v2_sessions)
        retry_creation = _create_v1(v1_service, parameter_name)
        result = mirror_policy_after_commit(
            retry_creation.snapshot,
            mirror_factory=lambda: mirror_service,
        )

        assert retry_creation.is_existing_policy is True
        assert result.mapping_created is True
    finally:
        _cleanup_v2(v2_engine, model_id)
        v1_engine.dispose()
        v2_engine.dispose()


def test_supabase_transaction_failure_rolls_back_and_has_no_background_repair() -> None:
    v2_engine = create_engine(_disposable_url())
    v2_sessions = sessionmaker(v2_engine, class_=Session, expire_on_commit=False)
    v1_engine, v1_service = _v1_service()
    model_id = None
    try:
        model_id, parameter_name = _seed_catalog(v2_sessions)
        creation = _create_v1(v1_service, parameter_name)

        class FailingMirror:
            def mirror_legacy_policy(self, snapshot):
                with v2_sessions.begin() as session:
                    mirror_legacy_policy_in_session(session, snapshot)
                    raise OperationalError(
                        "forced transaction failure",
                        {},
                        RuntimeError("forced"),
                    )

        with pytest.raises(PolicyMirrorUnavailableError):
            mirror_policy_after_commit(
                creation.snapshot,
                mirror_factory=FailingMirror,
            )

        with v2_sessions() as session:
            assert session.scalar(select(func.count()).select_from(Policy)) == 0
            assert (
                session.scalar(select(func.count()).select_from(LegacyPolicyMapping))
                == 0
            )
        with v1_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(V1Policy)) == 1

        # No process is scheduled to change this state. Only an explicit retry
        # invokes the mirror and creates the missing destination rows.
        with v2_sessions() as session:
            assert (
                session.scalar(select(func.count()).select_from(LegacyPolicyMapping))
                == 0
            )
        result = mirror_policy_after_commit(
            creation.snapshot,
            mirror_factory=lambda: V2PolicyService(PolicyDatabaseSession(v2_sessions)),
        )
        assert result.mapping_created is True
    finally:
        _cleanup_v2(v2_engine, model_id)
        v1_engine.dispose()
        v2_engine.dispose()
