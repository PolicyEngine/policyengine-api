"""PostgreSQL transaction tests for legacy saved-policy projection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
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
from policyengine_api.services.v2.user_policies.legacy_service import (
    resolve_legacy_user_id,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
)
from policyengine_api.services.v2.user_policies.legacy_service import (
    persist_legacy_user_policy,
)
from policyengine_api.services.v2.user_policies.legacy_translation import (
    LegacyUserPolicySnapshot,
    fingerprint_legacy_user_policy,
)


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
        pytest.fail("saved-policy mirror tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


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
            name="gov.phase10.saved_policy_rate",
            tax_benefit_model_version=version,
        )
        session.add(parameter)
        session.flush()
        return model.id, parameter.name


def _reform(parameter_name: str, *, legacy_id: int, source_hash: str):
    return LegacyPolicySnapshot(
        country_id="us",
        legacy_policy_id=legacy_id,
        label="Ignored legacy label",
        api_version=COUNTRY_PACKAGE_VERSIONS["us"],
        policy_json={parameter_name: {"2026": 0.2}},
        source_policy_hash=source_hash,
    )


def _saved(*, legacy_id: int, reform_id: int, reform_label="Reform", **changes):
    values = {
        "country_id": "us",
        "legacy_user_policy_id": legacy_id,
        "reform_id": reform_id,
        "reform_label": reform_label,
        "baseline_id": 1,
        "baseline_label": "Current law",
        "user_id": "auth0|one",
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
    return LegacyUserPolicySnapshot.model_validate(values)


def _cleanup(engine, model_id) -> None:
    if model_id is None:
        return
    with engine.begin() as connection:
        legacy_user_ids = ("auth0|one", "legacy-user-two")
        user_ids = (
            connection.execute(
                select(LegacyUserMapping.user_id).where(
                    LegacyUserMapping.legacy_user_id.in_(legacy_user_ids)
                )
            )
            .scalars()
            .all()
        )
        connection.execute(
            delete(LegacyUserMapping).where(
                LegacyUserMapping.legacy_user_id.in_(legacy_user_ids)
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


def test_saved_rows_share_policy_and_reuse_only_the_same_mapped_user() -> None:
    engine = create_engine(_disposable_url())
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    model_id = None
    try:
        model_id, parameter_name = _seed_catalog(sessions)
        first_reform = _reform(parameter_name, legacy_id=101, source_hash="first")
        second_reform = _reform(parameter_name, legacy_id=102, source_hash="second")
        first_saved = _saved(legacy_id=201, reform_id=101)
        second_saved = _saved(
            legacy_id=202,
            reform_id=102,
            reform_label=None,
        )
        third_saved = _saved(
            legacy_id=203,
            reform_id=101,
            reform_label="Other user",
            user_id="legacy-user-two",
        )

        with sessions.begin() as session:
            first = persist_legacy_user_policy(
                session,
                first_saved,
                first_reform,
                source_revision=1,
            )
            second = persist_legacy_user_policy(
                session,
                second_saved,
                second_reform,
                source_revision=1,
            )
            third = persist_legacy_user_policy(
                session,
                third_saved,
                first_reform,
                source_revision=1,
            )
        with sessions.begin() as session:
            retry = persist_legacy_user_policy(
                session,
                first_saved,
                first_reform,
                source_revision=1,
            )

        assert first.policy_id == second.policy_id
        assert first.association_id != second.association_id
        assert third.policy_id == first.policy_id
        assert retry.association_id == first.association_id
        assert retry.association_created is False
        with sessions() as session:
            associations = session.scalars(
                select(UserPolicy).order_by(UserPolicy.created_at, UserPolicy.id)
            ).all()
            assert {association.name for association in associations} == {
                "Reform",
                None,
                "Other user",
            }
            assert all(association.description is None for association in associations)
            association_by_id = {
                association.id: association for association in associations
            }
            assert association_by_id[first.association_id].user_id == (
                association_by_id[second.association_id].user_id
            )
            assert association_by_id[third.association_id].user_id != (
                association_by_id[first.association_id].user_id
            )
            assert session.scalar(select(func.count()).select_from(Policy)) == 1
            assert session.scalar(select(func.count()).select_from(User)) == 2
            assert (
                session.scalar(select(func.count()).select_from(LegacyUserMapping)) == 2
            )
            assert (
                session.scalar(select(func.count()).select_from(LegacyPolicyMapping))
                == 2
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(LegacyUserPolicyMapping)
                )
                == 3
            )
    finally:
        _cleanup(engine, model_id)
        engine.dispose()


def test_concurrent_first_use_resolves_one_legacy_user_mapping() -> None:
    engine = create_engine(_disposable_url())
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    legacy_user_id = f"phase10-concurrent-{uuid4()}"
    barrier = Barrier(2)

    def resolve() -> UUID:
        with sessions.begin() as session:
            barrier.wait()
            return resolve_legacy_user_id(
                session,
                legacy_user_id=legacy_user_id,
                primary_country="us",
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            user_ids = list(executor.map(lambda _index: resolve(), range(2)))

        assert user_ids[0] == user_ids[1]
        with sessions() as session:
            mappings = session.scalars(
                select(LegacyUserMapping).where(
                    LegacyUserMapping.legacy_user_id == legacy_user_id
                )
            ).all()
            assert len(mappings) == 1
            assert session.get(User, user_ids[0]) is not None
    finally:
        with sessions.begin() as session:
            mapping = session.get(LegacyUserMapping, legacy_user_id)
            if mapping is not None:
                user_id = mapping.user_id
                session.delete(mapping)
                session.flush()
                user = session.get(User, user_id)
                if user is not None:
                    session.delete(user)
        engine.dispose()


def test_label_and_v1_only_updates_advance_the_complete_row_fingerprint() -> None:
    engine = create_engine(_disposable_url())
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    model_id = None
    try:
        model_id, parameter_name = _seed_catalog(sessions)
        reform = _reform(parameter_name, legacy_id=301, source_hash="reform")
        original = _saved(legacy_id=401, reform_id=301)
        with sessions.begin() as session:
            created = persist_legacy_user_policy(
                session,
                original,
                reform,
                source_revision=1,
            )

        renamed = original.model_copy(
            update={"reform_label": "Renamed", "updated_date": 3}
        )
        with sessions.begin() as session:
            association = session.get(UserPolicy, created.association_id)
            association.description = "Native description"
        with sessions.begin() as session:
            rename_result = persist_legacy_user_policy(
                session,
                renamed,
                reform,
                source_revision=2,
                changed_fields=frozenset({"reform_label", "updated_date"}),
            )
        with sessions() as session:
            after_rename = session.get(UserPolicy, created.association_id)
            mapping = session.scalar(
                select(LegacyUserPolicyMapping).where(
                    LegacyUserPolicyMapping.user_policy_id == created.association_id
                )
            )
            assert after_rename.name == "Renamed"
            assert after_rename.description == "Native description"
            assert mapping.fingerprint_sha256 == fingerprint_legacy_user_policy(renamed)

        v1_only = renamed.model_copy(update={"year": "2027", "updated_date": 4})
        with sessions.begin() as session:
            association = session.get(UserPolicy, created.association_id)
            association.name = "Native name"
        with sessions() as session:
            native_timestamp = session.get(
                UserPolicy,
                created.association_id,
            ).updated_at
        with sessions.begin() as session:
            v1_only_result = persist_legacy_user_policy(
                session,
                v1_only,
                reform,
                source_revision=3,
                changed_fields=frozenset({"year", "updated_date"}),
            )
        with sessions() as session:
            association = session.get(UserPolicy, created.association_id)
            mapping = session.scalar(
                select(LegacyUserPolicyMapping).where(
                    LegacyUserPolicyMapping.user_policy_id == created.association_id
                )
            )

        assert rename_result.association_updated is True
        assert v1_only_result.association_updated is False
        assert association.name == "Native name"
        assert association.description == "Native description"
        assert association.updated_at == native_timestamp
        assert mapping.fingerprint_sha256 == fingerprint_legacy_user_policy(v1_only)
    finally:
        _cleanup(engine, model_id)
        engine.dispose()


def test_complete_transaction_rolls_back_and_native_delete_is_isolated() -> None:
    engine = create_engine(_disposable_url())
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    model_id = None
    try:
        model_id, parameter_name = _seed_catalog(sessions)
        reform = _reform(parameter_name, legacy_id=501, source_hash="rollback")
        saved = _saved(legacy_id=601, reform_id=501)
        with pytest.raises(RuntimeError, match="forced rollback"):
            with sessions.begin() as session:
                persist_legacy_user_policy(
                    session,
                    saved,
                    reform,
                    source_revision=1,
                )
                raise RuntimeError("forced rollback")

        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(Policy)) == 0
            assert session.scalar(select(func.count()).select_from(UserPolicy)) == 0
            assert session.scalar(select(func.count()).select_from(User)) == 0
            assert (
                session.scalar(select(func.count()).select_from(LegacyUserMapping)) == 0
            )
            assert (
                session.scalar(select(func.count()).select_from(LegacyPolicyMapping))
                == 0
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(LegacyUserPolicyMapping)
                )
                == 0
            )

        with sessions.begin() as session:
            created = persist_legacy_user_policy(
                session,
                saved,
                reform,
                source_revision=1,
            )
        with sessions.begin() as session:
            association = session.get(UserPolicy, created.association_id)
            session.delete(association)

        with sessions() as session:
            assert session.get(UserPolicy, created.association_id) is None
            assert (
                session.scalar(
                    select(func.count()).select_from(LegacyUserPolicyMapping)
                )
                == 0
            )
            assert session.get(Policy, created.policy_id) is not None
            assert session.scalar(select(func.count()).select_from(User)) == 1
            assert (
                session.scalar(select(func.count()).select_from(LegacyUserMapping)) == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ParameterValue)
                    .where(ParameterValue.policy_id == created.policy_id)
                )
                == 1
            )
    finally:
        _cleanup(engine, model_id)
        engine.dispose()
