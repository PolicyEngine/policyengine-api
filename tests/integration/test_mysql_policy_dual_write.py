"""Real MySQL JSON storage and PostgreSQL policy-mirroring regressions.

Opt in with ALEMBIC_DATABASE_URL pointing at local policyengine_alembic_test
and, for cross-database tests, V2_ALEMBIC_DISPOSABLE_TEST=1 plus
V2_MIGRATION_DATABASE_URL pointing at local policyengine_v2_alembic_test.
Prepare both schemas with their respective Alembic upgrades before running.
Only rows created by these fixtures are removed during cleanup.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DataError
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
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.services.policy_mirroring import (
    PolicyMirrorUnavailableError,
    mirror_policy_after_commit,
)
from policyengine_api.services.policy_service import PolicyService, PolicySetResult
from policyengine_api.services.v2.policies.database_session import PolicyDatabaseSession
from policyengine_api.services.v2.policies.services import V2PolicyService
from policyengine_api.services.v2.policies.types import (
    NativePolicyCreationInput,
    PolicyParameterValueInput,
)
from policyengine_api.services.v2.policies.validators import (
    LegacyPolicyMappingIntegrityError,
)
from policyengine_api.utils import hash_object

INPUT_VALUE = 0.04 + 3 / 1_000_000
STORED_VALUE = 0.040003
PARAMETER_NAME = "gov.phase10.mysql_storage_rate"
PERIOD = "2026-01-01.2100-12-31"


def _mysql_url() -> str:
    database_url = os.environ.get("ALEMBIC_DATABASE_URL", "")
    if not database_url:
        pytest.skip("ALEMBIC_DATABASE_URL is not set")
    url = make_url(database_url)
    if (
        url.drivername != "mysql+pymysql"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database != "policyengine_alembic_test"
        or not url.username
        or url.password is None
    ):
        pytest.fail(
            "MySQL mirror tests require explicit test credentials and the local "
            "mysql+pymysql policyengine_alembic_test schema"
        )
    return database_url


def _postgres_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    if os.environ.get(V2_ALEMBIC_DISPOSABLE_TEST) != "1":
        pytest.fail("MySQL mirror tests require v2 disposable-test mode")
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: database_url,
            V2_ALEMBIC_DISPOSABLE_TEST: "1",
        }
    )
    return settings.url.render_as_string(hide_password=False)


@dataclass
class MySQLSource:
    engine: Engine
    service: PolicyService
    label_prefix: str

    def create(self, label: str = "first") -> PolicySetResult:
        return self.service.set_policy(
            "us",
            f"{self.label_prefix}{label}",
            {PARAMETER_NAME: {PERIOD: INPUT_VALUE}},
            prepare_for_mirroring=True,
        )


@pytest.fixture
def mysql_source():
    engine = create_engine(_mysql_url())
    source = MySQLSource(
        engine,
        PolicyService(sessionmaker(engine, expire_on_commit=False)),
        f"mysql-mirror-{uuid4().hex}-",
    )
    try:
        yield source
    finally:
        try:
            with engine.begin() as connection:
                connection.execute(
                    delete(V1Policy).where(
                        V1Policy.label.startswith(source.label_prefix, autoescape=True)
                    )
                )
        finally:
            engine.dispose()


@dataclass
class PostgreSQLDestination:
    sessions: sessionmaker
    service: V2PolicyService
    model_id: UUID

    def mirror(self, creation: PolicySetResult):
        assert creation.snapshot is not None
        return mirror_policy_after_commit(
            creation.snapshot,
            mirror_factory=lambda: self.service,
        )

    def counts(self) -> tuple[int, int, int]:
        policy_ids = select(Policy.id).where(
            Policy.tax_benefit_model_id == self.model_id
        )
        with self.sessions() as session:
            return tuple(
                session.scalar(select(func.count()).select_from(table).where(clause))
                for table, clause in (
                    (Policy, Policy.id.in_(policy_ids)),
                    (ParameterValue, ParameterValue.policy_id.in_(policy_ids)),
                    (
                        LegacyPolicyMapping,
                        LegacyPolicyMapping.policy_id.in_(policy_ids),
                    ),
                )
            )


@pytest.fixture
def postgres_destination():
    engine = create_engine(_postgres_url())
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    model_id = None
    try:
        with sessions.begin() as session:
            model = TaxBenefitModel(name="policyengine-us")
            version = TaxBenefitModelVersion(
                model=model,
                version=POLICYENGINE_VERSION,
                current_law_id=1,
                metadata_time_periods=[2026],
            )
            session.add(
                Parameter(
                    name=PARAMETER_NAME,
                    tax_benefit_model_version=version,
                )
            )
            session.flush()
            model_id = model.id
        yield PostgreSQLDestination(
            sessions, V2PolicyService(PolicyDatabaseSession(sessions)), model_id
        )
    finally:
        try:
            if model_id is not None:
                with engine.begin() as connection:
                    policy_ids = select(Policy.id).where(
                        Policy.tax_benefit_model_id == model_id
                    )
                    version_ids = select(TaxBenefitModelVersion.id).where(
                        TaxBenefitModelVersion.model_id == model_id
                    )
                    for table, clause in (
                        (
                            LegacyPolicyMapping,
                            LegacyPolicyMapping.policy_id.in_(policy_ids),
                        ),
                        (ParameterValue, ParameterValue.policy_id.in_(policy_ids)),
                        (Policy, Policy.tax_benefit_model_id == model_id),
                        (
                            Parameter,
                            Parameter.tax_benefit_model_version_id.in_(version_ids),
                        ),
                        (
                            TaxBenefitModelVersion,
                            TaxBenefitModelVersion.model_id == model_id,
                        ),
                        (TaxBenefitModel, TaxBenefitModel.id == model_id),
                    ):
                        connection.execute(delete(table).where(clause))
        finally:
            engine.dispose()


def test_first_snapshot_matches_real_mysql_json_storage(
    mysql_source, record_property
) -> None:
    creation = mysql_source.create()
    assert creation.snapshot is not None
    with mysql_source.engine.connect() as connection:
        raw_json = connection.execute(
            text("SELECT policy_json FROM policy WHERE id = :id AND country_id = 'us'"),
            {"id": creation.policy_id},
        ).scalar_one()
    persisted = json.loads(raw_json)
    record_property("input_value", repr(INPUT_VALUE))
    record_property("mysql_policy_json", raw_json)
    record_property("mysql_legacy_policy_id", creation.policy_id)

    # This assertion makes the regression sensitive to actual MySQL storage;
    # a SQLite replacement or a backend preserving the input is insufficient.
    assert repr(INPUT_VALUE) == "0.040003000000000004"
    assert persisted == {PARAMETER_NAME: {PERIOD: STORED_VALUE}}
    assert persisted[PARAMETER_NAME][PERIOD] != INPUT_VALUE
    assert creation.snapshot.policy_json == persisted
    assert creation.snapshot.source_policy_hash == hash_object(
        {PARAMETER_NAME: {PERIOD: INPUT_VALUE}}
    )
    assert creation.snapshot == mysql_source.service.get_policy_snapshot(
        "us", creation.policy_id
    )


@pytest.mark.parametrize("fail_destination", [False, True], ids=["success", "rollback"])
def test_mysql_first_write_retry_and_relabel_keep_one_postgres_uuid(
    mysql_source, postgres_destination, fail_destination, record_property
) -> None:
    creation = mysql_source.create()
    assert creation.is_existing_policy is False
    assert creation.snapshot == mysql_source.service.get_policy_snapshot(
        "us", creation.policy_id
    )
    assert creation.snapshot.policy_json == {PARAMETER_NAME: {PERIOD: STORED_VALUE}}

    if fail_destination:

        class FailingTransaction(PolicyDatabaseSession):
            @contextmanager
            def transaction(self):
                with super().transaction() as session:
                    yield session
                    # Fail on the real server after policy/value/mapping inserts
                    # and before COMMIT, exercising PostgreSQL rollback itself.
                    session.execute(text("SELECT 1 / 0"))

        failing_service = V2PolicyService(
            FailingTransaction(postgres_destination.sessions)
        )
        with pytest.raises(PolicyMirrorUnavailableError) as failure:
            mirror_policy_after_commit(
                creation.snapshot, mirror_factory=lambda: failing_service
            )
        assert isinstance(failure.value.__cause__, DataError)
        assert postgres_destination.counts() == (0, 0, 0)
        assert mysql_source.service.get_policy("us", creation.policy_id) is not None
        first = None
    else:
        first = postgres_destination.mirror(creation)
        assert first.policy_created is True
        assert first.mapping_created is True

    # Repeat the real source service call, including a new MySQL session, as an
    # HTTP retry would after destination failure or a lost successful response.
    retry_creation = mysql_source.create()
    assert retry_creation.is_existing_policy is True
    assert retry_creation.policy_id == creation.policy_id
    assert retry_creation.snapshot == creation.snapshot
    retry = postgres_destination.mirror(retry_creation)
    assert retry.policy_created is fail_destination
    assert retry.mapping_created is fail_destination
    if first is not None:
        assert retry.policy_id == first.policy_id

    relabeled = mysql_source.create("relabeled")
    assert relabeled.is_existing_policy is False
    assert relabeled.policy_id != creation.policy_id
    assert relabeled.snapshot.policy_json == creation.snapshot.policy_json
    assert relabeled.snapshot.source_policy_hash == creation.snapshot.source_policy_hash
    relabel_result = postgres_destination.mirror(relabeled)
    record_property("mysql_first_legacy_policy_id", creation.policy_id)
    record_property("mysql_retry_legacy_policy_id", retry_creation.policy_id)
    record_property("mysql_relabel_legacy_policy_id", relabeled.policy_id)
    record_property(
        "postgres_first_policy_id",
        "rolled_back" if first is None else str(first.policy_id),
    )
    record_property("postgres_retry_policy_id", str(retry.policy_id))
    record_property("postgres_relabel_policy_id", str(relabel_result.policy_id))
    assert relabel_result.policy_id == retry.policy_id
    assert relabel_result.policy_created is False
    assert relabel_result.mapping_created is True
    assert (
        postgres_destination.mirror(mysql_source.create()).policy_id == retry.policy_id
    )
    assert (
        postgres_destination.mirror(mysql_source.create("relabeled")).policy_id
        == retry.policy_id
    )
    assert postgres_destination.counts() == (1, 1, 2)
    with postgres_destination.sessions() as session:
        mappings = session.scalars(
            select(LegacyPolicyMapping).where(
                LegacyPolicyMapping.policy_id == retry.policy_id
            )
        ).all()
        assert {row.legacy_policy_id for row in mappings} == {
            creation.policy_id,
            relabeled.policy_id,
        }
        assert {row.source_policy_hash for row in mappings} == {
            creation.snapshot.source_policy_hash
        }


def test_native_postgres_policies_preserve_the_distinct_input_number(
    mysql_source, postgres_destination, record_property
) -> None:
    mirrored = postgres_destination.mirror(mysql_source.create())
    item = postgres_destination.service.get_policy(
        country_id="us", policy_id=mirrored.policy_id
    )
    parameter = item.parameter_values[0]
    assert parameter.value == STORED_VALUE

    def create_native(value):
        return postgres_destination.service.create_policy(
            NativePolicyCreationInput(
                country_id="us",
                tax_benefit_model_id=postgres_destination.model_id,
                parameter_values=[
                    PolicyParameterValueInput(
                        parameter_id=parameter.parameter_id,
                        value=value,
                        start_date=parameter.start_date,
                        end_date=parameter.end_date,
                    )
                ],
            )
        )

    stored = create_native(STORED_VALUE)
    distinct = create_native(INPUT_VALUE)
    record_property("stored_value", repr(STORED_VALUE))
    record_property("distinct_input_value", repr(INPUT_VALUE))
    record_property("postgres_stored_policy_id", str(stored.item.id))
    record_property("postgres_distinct_policy_id", str(distinct.item.id))
    assert stored.created is False
    assert stored.item.id == mirrored.policy_id
    assert distinct.created is True
    assert distinct.item.id != mirrored.policy_id
    assert distinct.item.parameter_values[0].value == INPUT_VALUE
    assert create_native(INPUT_VALUE).item.id == distinct.item.id
    assert postgres_destination.counts() == (2, 2, 1)


def test_historical_pre_storage_mapping_is_rejected_without_repair(
    mysql_source, postgres_destination, record_property
) -> None:
    creation = mysql_source.create()
    assert creation.snapshot is not None
    assert creation.snapshot.policy_json == {PARAMETER_NAME: {PERIOD: STORED_VALUE}}
    # Reproduce the old first-write snapshot in disposable PostgreSQL only.
    historical = creation.snapshot.model_copy(
        update={"policy_json": {PARAMETER_NAME: {PERIOD: INPUT_VALUE}}}
    )
    original = mirror_policy_after_commit(
        historical, mirror_factory=lambda: postgres_destination.service
    )
    retry = mysql_source.create()
    assert retry.snapshot.source_policy_hash == historical.source_policy_hash
    assert retry.snapshot.legacy_policy_id == historical.legacy_policy_id
    assert retry.snapshot.policy_json != historical.policy_json

    with pytest.raises(PolicyMirrorUnavailableError) as failure:
        postgres_destination.mirror(retry)
    assert isinstance(failure.value.__cause__, LegacyPolicyMappingIntegrityError)
    assert "translated immutable content" in str(failure.value.__cause__)
    record_property("mysql_legacy_policy_id", creation.policy_id)
    record_property("postgres_historical_policy_id", str(original.policy_id))
    record_property("retry_error", type(failure.value.__cause__).__name__)
    assert postgres_destination.counts() == (1, 1, 1)
    with postgres_destination.sessions() as session:
        mapping = session.scalar(
            select(LegacyPolicyMapping).where(
                LegacyPolicyMapping.country_id == "us",
                LegacyPolicyMapping.legacy_policy_id == creation.policy_id,
            )
        )
        assert mapping.policy_id == original.policy_id
        assert mapping.source_policy_hash == historical.source_policy_hash
        assert (
            session.scalar(
                select(ParameterValue.value_json).where(
                    ParameterValue.policy_id == original.policy_id
                )
            )
            == INPUT_VALUE
        )
