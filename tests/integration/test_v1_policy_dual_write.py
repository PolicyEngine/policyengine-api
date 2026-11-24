"""Cross-database transaction tests for immediate v1 policy mirroring."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError

from policyengine_api.constants import POLICYENGINE_VERSION
from policyengine_api.data.v1_models import Policy as V1Policy
from policyengine_api.data.v2.models import (
    LegacyPolicyMapping,
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.policy_mirroring import (
    PolicyMirrorUnavailableError,
    mirror_policy_after_commit,
)
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import (
    V2PolicyService,
    mirror_legacy_policy_in_session,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as OrmSession
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session


def _v1_service(v1_sessions: sessionmaker[OrmSession]) -> PolicyService:
    _cleanup_v1(v1_sessions)
    return PolicyService(v1_sessions)


def _cleanup_v1(v1_sessions: sessionmaker[OrmSession]) -> None:
    with v1_sessions.begin() as session:
        session.execute(delete(V1Policy))


def _seed_catalog(
    v2_owner_sessions: sessionmaker[Session], country_id: str = "us"
) -> tuple[object, str]:
    with v2_owner_sessions.begin() as session:
        model = TaxBenefitModel(name=f"policyengine-{country_id}")
        version = TaxBenefitModelVersion(
            model=model,
            version=POLICYENGINE_VERSION,
            current_law_id=1,
            metadata_time_periods=[2026],
        )
        parameter = Parameter(
            name=f"gov.phase10.{country_id}.cross_database_rate",
            tax_benefit_model_version=version,
        )
        session.add(parameter)
        session.flush()
        return model.id, parameter.name


def _cleanup_v2(v2_owner_sessions: sessionmaker[Session], model_id) -> None:
    if model_id is None:
        return
    with v2_owner_sessions.begin() as session:
        policy_ids = select(Policy.id).where(Policy.tax_benefit_model_id == model_id)
        session.execute(
            delete(LegacyPolicyMapping).where(
                LegacyPolicyMapping.policy_id.in_(policy_ids)
            )
        )
        session.execute(
            delete(ParameterValue).where(ParameterValue.policy_id.in_(policy_ids))
        )
        session.execute(delete(Policy).where(Policy.tax_benefit_model_id == model_id))
        version_ids = select(TaxBenefitModelVersion.id).where(
            TaxBenefitModelVersion.model_id == model_id
        )
        session.execute(
            delete(Parameter).where(
                Parameter.tax_benefit_model_version_id.in_(version_ids)
            )
        )
        session.execute(
            delete(TaxBenefitModelVersion).where(
                TaxBenefitModelVersion.model_id == model_id
            )
        )
        session.execute(delete(TaxBenefitModel).where(TaxBenefitModel.id == model_id))


def _create_v1(
    service: PolicyService,
    parameter_name: str,
    country_id: str = "us",
):
    return service.set_policy(
        country_id,
        "Cross-database policy",
        {parameter_name: {"2026": 0.2}},
        prepare_for_mirroring=True,
    )


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_both_commits_and_interrupted_response_retry_resolve_one_mapping(
    country_id: str,
    v1_sessions: sessionmaker[OrmSession],
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    v1_service = _v1_service(v1_sessions)
    model_id = None
    try:
        model_id, parameter_name = _seed_catalog(v2_owner_sessions, country_id)
        mirror_service = V2PolicyService(PolicyDatabaseSession(v2_owner_sessions))
        creation = _create_v1(v1_service, parameter_name, country_id)
        first = mirror_policy_after_commit(
            creation.snapshot,
            mirror_factory=lambda: mirror_service,
        )

        # Simulate losing the HTTP response after both commits by repeating the
        # exact create and mirror operations.
        retry_creation = _create_v1(v1_service, parameter_name, country_id)
        retry = mirror_policy_after_commit(
            retry_creation.snapshot,
            mirror_factory=lambda: mirror_service,
        )

        assert creation.is_existing_policy is False
        assert retry_creation.is_existing_policy is True
        assert retry.policy_id == first.policy_id
        with v2_owner_sessions() as session:
            assert (
                session.scalar(select(func.count()).select_from(LegacyPolicyMapping))
                == 1
            )
            assert session.scalar(select(func.count()).select_from(Policy)) == 1
        assert v1_service.get_policy(country_id, creation.policy_id) is not None
    finally:
        _cleanup_v2(v2_owner_sessions, model_id)
        _cleanup_v1(v1_sessions)


def test_catalog_failure_leaves_cloud_sql_committed_and_retry_completes(
    v1_sessions: sessionmaker[OrmSession],
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    v1_service = _v1_service(v1_sessions)
    model_id = None
    parameter_name = "gov.phase10.us.cross_database_rate"
    try:
        creation = _create_v1(v1_service, parameter_name)
        mirror_service = V2PolicyService(PolicyDatabaseSession(v2_owner_sessions))

        with pytest.raises(PolicyMirrorUnavailableError):
            mirror_policy_after_commit(
                creation.snapshot,
                mirror_factory=lambda: mirror_service,
            )

        assert v1_service.get_policy("us", creation.policy_id) is not None
        with v2_owner_sessions() as session:
            assert (
                session.scalar(select(func.count()).select_from(LegacyPolicyMapping))
                == 0
            )

        model_id, _parameter_name = _seed_catalog(v2_owner_sessions)
        retry_creation = _create_v1(v1_service, parameter_name)
        result = mirror_policy_after_commit(
            retry_creation.snapshot,
            mirror_factory=lambda: mirror_service,
        )

        assert retry_creation.is_existing_policy is True
        assert result.mapping_created is True
    finally:
        _cleanup_v2(v2_owner_sessions, model_id)
        _cleanup_v1(v1_sessions)


def test_supabase_transaction_failure_rolls_back_and_has_no_background_repair(
    v1_sessions: sessionmaker[OrmSession],
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    v1_service = _v1_service(v1_sessions)
    model_id = None
    try:
        model_id, parameter_name = _seed_catalog(v2_owner_sessions)
        creation = _create_v1(v1_service, parameter_name)

        class FailingMirror:
            def mirror_legacy_policy(self, snapshot):
                with v2_owner_sessions.begin() as session:
                    mirror_legacy_policy_in_session(session, snapshot)
                    msg = "forced transaction failure"
                    raise OperationalError(
                        msg,
                        {},
                        RuntimeError("forced"),
                    )

        with pytest.raises(PolicyMirrorUnavailableError):
            mirror_policy_after_commit(
                creation.snapshot,
                mirror_factory=FailingMirror,
            )

        with v2_owner_sessions() as session:
            assert session.scalar(select(func.count()).select_from(Policy)) == 0
            assert (
                session.scalar(select(func.count()).select_from(LegacyPolicyMapping))
                == 0
            )
        with v1_sessions() as v1_session:
            assert v1_session.scalar(select(func.count()).select_from(V1Policy)) == 1

        # No process is scheduled to change this state. Only an explicit retry
        # invokes the mirror and creates the missing destination rows.
        with v2_owner_sessions() as session:
            assert (
                session.scalar(select(func.count()).select_from(LegacyPolicyMapping))
                == 0
            )
        result = mirror_policy_after_commit(
            creation.snapshot,
            mirror_factory=lambda: V2PolicyService(
                PolicyDatabaseSession(v2_owner_sessions)
            ),
        )
        assert result.mapping_created is True
    finally:
        _cleanup_v2(v2_owner_sessions, model_id)
        _cleanup_v1(v1_sessions)
