"""PostgreSQL transaction tests for immutable policy persistence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

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
from policyengine_api.data.v2.policies.canonicalization import (
    CanonicalPolicyContent,
    canonical_policy_document,
    canonicalize_policy,
)
from policyengine_api.data.v2.policies.legacy_mapping_repository import (
    LegacyPolicyMappingIntegrityError,
)
from policyengine_api.data.v2.policies.write_repository import (
    PolicyContentHashCollisionError,
    persist_resolved_policy,
)
from policyengine_api.services.v2.policies.commands import (
    ResolvedPolicyCreateCommand,
)
from policyengine_api.services.v2.policies.legacy_service import (
    persist_legacy_policy,
)
from policyengine_api.services.v2.policies.legacy_translation import (
    LegacyPolicySnapshot,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL


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
        pytest.fail("policy persistence tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


def _catalog(session: Session, *, country_id: str | None = None):
    unique = uuid4().hex
    model = TaxBenefitModel(
        name=(
            f"policyengine-{country_id}"
            if country_id is not None
            else f"phase10-policy-{unique[:8]}"
        )
    )
    version = TaxBenefitModelVersion(
        model=model,
        version="5.2.0",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    parameter = Parameter(
        name=f"gov.phase10.{unique}",
        tax_benefit_model_version=version,
    )
    session.add(parameter)
    session.flush()
    return model, version, parameter


def _command(
    model_id: UUID,
    version_id: UUID,
    parameter_id: UUID,
    *,
    value: object = 0.2,
) -> ResolvedPolicyCreateCommand:
    return ResolvedPolicyCreateCommand(
        country_id="us",
        tax_benefit_model_id=model_id,
        tax_benefit_model_version_id=version_id,
        policyengine_version="5.2.0",
        parameter_values=[
            {
                "parameter_id": parameter_id,
                "value": value,
                "start_date": "2026-01-01T00:00:00Z",
            }
        ],
    )


def _cleanup(engine, model_id: UUID) -> None:
    with engine.begin() as connection:
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


def test_equivalent_create_returns_one_policy_and_one_child_set() -> None:
    engine = create_engine(_disposable_url())
    model_id = None
    try:
        with Session(engine) as session, session.begin():
            model, version, parameter = _catalog(session)
            model_id = model.id
            command = _command(model.id, version.id, parameter.id)
            first = persist_resolved_policy(session, command)

        with Session(engine) as session, session.begin():
            second = persist_resolved_policy(session, command)

        assert first.created is True
        assert second.created is False
        assert second.policy_id == first.policy_id

        with Session(engine) as session:
            policy_count = session.scalar(
                select(func.count())
                .select_from(Policy)
                .where(Policy.id == first.policy_id)
            )
            value_count = session.scalar(
                select(func.count())
                .select_from(ParameterValue)
                .where(ParameterValue.policy_id == first.policy_id)
            )
        assert (policy_count, value_count) == (1, 1)
    finally:
        if model_id is not None:
            _cleanup(engine, model_id)
        engine.dispose()


def test_equal_hash_with_different_canonical_bytes_is_an_integrity_error() -> None:
    engine = create_engine(_disposable_url())
    model_id = None
    try:
        with Session(engine) as session, session.begin():
            model, version, parameter = _catalog(session)
            model_id = model.id
            version_id = version.id
            parameter_id = parameter.id
            original = _command(model_id, version_id, parameter_id, value=0.2)
            stored = canonicalize_policy(original)
            persist_resolved_policy(session, original)

        changed = _command(model_id, version_id, parameter_id, value=0.3)

        def simulated_collision(
            command: ResolvedPolicyCreateCommand,
        ) -> CanonicalPolicyContent:
            return CanonicalPolicyContent(
                version=stored.version,
                document=canonical_policy_document(command),
                content_hash=stored.content_hash,
            )

        with Session(engine) as session, session.begin():
            with pytest.raises(PolicyContentHashCollisionError):
                persist_resolved_policy(
                    session,
                    changed,
                    canonicalizer=simulated_collision,
                )

        with Session(engine) as session:
            values = session.scalars(
                select(ParameterValue.value_json)
                .join(
                    Policy,
                    Policy.id == ParameterValue.policy_id,
                )
                .where(Policy.tax_benefit_model_id == model_id)
            ).all()
        assert values == [0.2]
    finally:
        if model_id is not None:
            _cleanup(engine, model_id)
        engine.dispose()


def test_legacy_policy_mapping_is_many_to_one_and_retry_safe() -> None:
    engine = create_engine(_disposable_url())
    model_id = None
    try:
        with Session(engine) as session, session.begin():
            model, version, parameter = _catalog(session, country_id="us")
            model_id = model.id
            first = LegacyPolicySnapshot(
                country_id="us",
                legacy_policy_id=301,
                label="First label",
                api_version="1.0.0",
                policy_json={parameter.name: {"2026": 0.2}},
                source_policy_hash="first-legacy-hash",
            )
            second = LegacyPolicySnapshot(
                country_id="us",
                legacy_policy_id=302,
                label="Second label",
                api_version="1.0.0",
                policy_json={parameter.name: {"2026": 0.2}},
                source_policy_hash="second-legacy-hash",
            )
            first_result = persist_legacy_policy(
                session,
                first,
                running_policyengine_version=version.version,
                country_package_versions={"us": "1.0.0"},
            )
            second_result = persist_legacy_policy(
                session,
                second,
                running_policyengine_version=version.version,
                country_package_versions={"us": "1.0.0"},
            )

        with Session(engine) as session, session.begin():
            retry = persist_legacy_policy(
                session,
                first,
                running_policyengine_version="5.2.0",
                country_package_versions={"us": "1.0.0"},
            )

        assert first_result.policy_id == second_result.policy_id == retry.policy_id
        assert first_result.policy_created is True
        assert second_result.policy_created is False
        assert retry == type(retry)(
            policy_id=first_result.policy_id,
            policy_created=False,
            mapping_created=False,
        )
        with Session(engine) as session:
            mappings = session.scalars(
                select(LegacyPolicyMapping).where(
                    LegacyPolicyMapping.policy_id == first_result.policy_id
                )
            ).all()
        assert {mapping.legacy_policy_id for mapping in mappings} == {301, 302}
    finally:
        if model_id is not None:
            _cleanup(engine, model_id)
        engine.dispose()


def test_changed_hash_for_one_legacy_identity_rolls_back_without_mutation() -> None:
    engine = create_engine(_disposable_url())
    model_id = None
    try:
        with Session(engine) as session, session.begin():
            model, version, parameter = _catalog(session, country_id="us")
            model_id = model.id
            parameter_name = parameter.name
            snapshot = LegacyPolicySnapshot(
                country_id="us",
                legacy_policy_id=401,
                api_version="1.0.0",
                policy_json={parameter_name: {"2026": 0.2}},
                source_policy_hash="committed-source-hash",
            )
            result = persist_legacy_policy(
                session,
                snapshot,
                running_policyengine_version=version.version,
                country_package_versions={"us": "1.0.0"},
            )

        changed = snapshot.model_copy(
            update={
                "source_policy_hash": "different-source-hash",
                "policy_json": {parameter_name: {"2026": 0.3}},
            }
        )
        with pytest.raises(LegacyPolicyMappingIntegrityError, match="different"):
            with Session(engine) as session, session.begin():
                persist_legacy_policy(
                    session,
                    changed,
                    running_policyengine_version="5.2.0",
                    country_package_versions={"us": "1.0.0"},
                )

        with Session(engine) as session:
            mapping = session.scalar(
                select(LegacyPolicyMapping).where(
                    LegacyPolicyMapping.legacy_policy_id == 401
                )
            )
            policy_count = session.scalar(
                select(func.count())
                .select_from(Policy)
                .where(Policy.tax_benefit_model_id == model_id)
            )
        assert mapping is not None
        assert mapping.policy_id == result.policy_id
        assert mapping.source_policy_hash == "committed-source-hash"
        assert policy_count == 1
    finally:
        if model_id is not None:
            _cleanup(engine, model_id)
        engine.dispose()


def test_concurrent_equivalent_creates_return_one_policy_uuid() -> None:
    engine = create_engine(_disposable_url())
    model_id = None
    try:
        with Session(engine) as session, session.begin():
            model, version, parameter = _catalog(session)
            model_id = model.id
            command = _command(model.id, version.id, parameter.id)

        barrier = Barrier(2, timeout=10)

        def create():
            with Session(engine) as session, session.begin():
                barrier.wait()
                return persist_resolved_policy(session, command)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]

        assert {result.policy_id for result in results} == {results[0].policy_id}
        assert sorted(result.created for result in results) == [False, True]
        with Session(engine) as session:
            policy_count = session.scalar(
                select(func.count())
                .select_from(Policy)
                .where(Policy.tax_benefit_model_id == model_id)
            )
            value_count = session.scalar(
                select(func.count())
                .select_from(ParameterValue)
                .where(ParameterValue.policy_id == results[0].policy_id)
            )
        assert (policy_count, value_count) == (1, 1)
    finally:
        if model_id is not None:
            _cleanup(engine, model_id)
        engine.dispose()


def test_empty_and_distinct_policy_content_persist_independently() -> None:
    engine = create_engine(_disposable_url())
    model_id = None
    try:
        with Session(engine) as session, session.begin():
            model, version, parameter = _catalog(session)
            model_id = model.id
            empty = ResolvedPolicyCreateCommand(
                country_id="us",
                tax_benefit_model_id=model.id,
                tax_benefit_model_version_id=version.id,
                policyengine_version=version.version,
                parameter_values=[],
            )
            first = persist_resolved_policy(session, empty)
            second = persist_resolved_policy(
                session,
                _command(model.id, version.id, parameter.id, value=1),
            )
            third = persist_resolved_policy(
                session,
                _command(model.id, version.id, parameter.id, value=2),
            )

        assert len({first.policy_id, second.policy_id, third.policy_id}) == 3
        with Session(engine) as session:
            empty_value_count = session.scalar(
                select(func.count())
                .select_from(ParameterValue)
                .where(ParameterValue.policy_id == first.policy_id)
            )
        assert empty_value_count == 0
    finally:
        if model_id is not None:
            _cleanup(engine, model_id)
        engine.dispose()


def test_child_insert_failure_rolls_back_the_policy_and_all_values() -> None:
    engine = create_engine(_disposable_url())
    model_id = None
    try:
        with Session(engine) as session, session.begin():
            model, version, _parameter = _catalog(session)
            model_id = model.id
            invalid = _command(model.id, version.id, uuid4())
            content_hash = canonicalize_policy(invalid).content_hash

        with pytest.raises(IntegrityError):
            with Session(engine) as session, session.begin():
                persist_resolved_policy(session, invalid)

        with Session(engine) as session:
            policy_count = session.scalar(
                select(func.count())
                .select_from(Policy)
                .where(Policy.content_hash == content_hash)
            )
            owned_value_count = session.scalar(
                select(func.count())
                .select_from(ParameterValue)
                .where(ParameterValue.policy_id.is_not(None))
            )
        assert policy_count == 0
        assert owned_value_count == 0
    finally:
        if model_id is not None:
            _cleanup(engine, model_id)
        engine.dispose()
