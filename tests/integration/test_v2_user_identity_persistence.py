"""PostgreSQL tests for signed-in identity provisioning and user associations.

These prove the behaviors SQLite cannot: named ``ON CONFLICT`` targets,
concurrent first sign-in, concurrent idempotent imports, ``MATCH SIMPLE``
composite keys with NULL references, and cascading account deletion.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    User,
    UserIdentity,
    UserPolicy,
    UserReportAssociation,
)
from policyengine_api.data.v2.settings import (
    V2_MIGRATION_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
)
from policyengine_api.data.v2 import user_association_migration_qualification
from policyengine_api.services.v2.identity.services import (
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_accounts.types import AccountImportInput
from tests.unit.v2.user_service_support import default_legacy_references


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: database_url,
            V2_ALEMBIC_DISPOSABLE_TEST: os.environ.get(V2_ALEMBIC_DISPOSABLE_TEST, ""),
        }
    )
    if not settings.disposable_test:
        pytest.fail("identity persistence tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(_disposable_url(), pool_size=10, max_overflow=10)
    factory = sessionmaker(engine, class_=Session, expire_on_commit=False)
    issuer = f"https://stage12a-{uuid4().hex[:12]}.example.test/"
    factory.kw["info"] = {"issuer": issuer}
    try:
        yield factory
    finally:
        with engine.begin() as connection:
            owned = select(UserIdentity.user_id).where(UserIdentity.issuer == issuer)
            user_ids = list(connection.execute(owned).scalars())
            if user_ids:
                connection.execute(
                    delete(LegacyUserMapping).where(
                        LegacyUserMapping.user_id.in_(user_ids)
                    )
                )
                connection.execute(delete(User).where(User.id.in_(user_ids)))
        engine.dispose()


def _principal(sessions, subject: str) -> UserPrincipal:
    return UserPrincipal(issuer=sessions.kw["info"]["issuer"], subject=subject)


def _count(sessions, statement) -> int:
    with sessions() as session:
        return int(session.execute(statement).scalar_one())


def test_concurrent_first_requests_provision_exactly_one_user(sessions) -> None:
    principal = _principal(sessions, "google-oauth2|race")
    workers = 8
    barrier = Barrier(workers)

    def first_request(_index: int):
        barrier.wait()
        with sessions.begin() as session:
            return resolve_principal_user_in_session(
                session, principal, country_id="us"
            ).user_id

    with ThreadPoolExecutor(max_workers=workers) as executor:
        user_ids = set(executor.map(first_request, range(workers)))

    assert len(user_ids) == 1
    issuer = principal.issuer
    assert (
        _count(
            sessions,
            select(func.count())
            .select_from(UserIdentity)
            .where(UserIdentity.issuer == issuer),
        )
        == 1
    )
    assert (
        _count(
            sessions,
            select(func.count()).select_from(User).where(User.id.in_(user_ids)),
        )
        == 1
    )


def test_concurrent_imports_are_idempotent_on_client_ref(sessions) -> None:
    principal = _principal(sessions, "google-oauth2|importer")
    service = V2AccountService(
        AccountDatabaseSession(sessions),
        legacy_references=default_legacy_references(),
    )
    service.get_account(principal=principal, country_id="us")
    request = AccountImportInput.model_validate(
        {
            "policies": [
                {"client_ref": f"sup-{index}", "legacy_policy_id": 1}
                for index in range(5)
            ],
            "simulations": [{"client_ref": "sus-1", "legacy_simulation_id": 613}],
            "reports": [
                {
                    "client_ref": "sur-1",
                    "legacy_report_id": 615,
                    "user_policy_client_ref": "sup-0",
                }
            ],
        }
    )
    workers = 4
    barrier = Barrier(workers)

    def import_records(_index: int):
        barrier.wait()
        return service.import_records(
            principal=principal, country_id="us", import_input=request
        ).id_map

    with ThreadPoolExecutor(max_workers=workers) as executor:
        id_maps = list(executor.map(import_records, range(workers)))

    assert all(id_map == id_maps[0] for id_map in id_maps)
    assert len(id_maps[0]) == 7
    with sessions() as session:
        owner = session.execute(
            select(UserIdentity.user_id).where(UserIdentity.issuer == principal.issuer)
        ).scalar_one()
        assert (
            session.execute(
                select(func.count())
                .select_from(UserPolicy)
                .where(UserPolicy.user_id == owner)
            ).scalar_one()
            == 5
        )
        report = session.get(UserReportAssociation, id_maps[0]["sur-1"])
        assert report is not None
        assert report.user_policy_id == id_maps[0]["sup-0"]


def test_reference_checks_and_match_simple_composite_keys(sessions) -> None:
    principal = _principal(sessions, "google-oauth2|constraints")
    with sessions.begin() as session:
        owner = resolve_principal_user_in_session(
            session, principal, country_id="us"
        ).user_id

    with sessions.begin() as session:
        session.add_all(
            [
                UserPolicy(user_id=owner, country_id="us", legacy_policy_id=1),
                UserPolicy(user_id=owner, country_id="us", legacy_policy_id=2),
            ]
        )

    for invalid in (
        UserPolicy(user_id=owner, country_id="us"),
        UserPolicy(user_id=owner, country_id="us", legacy_policy_id=1, baseline="x"),
        UserPolicy(user_id=owner, country_id="ca", legacy_policy_id=1),
        UserPolicy(user_id=owner, country_id="us", policy_id=uuid4()),
    ):
        with pytest.raises(IntegrityError):
            with sessions.begin() as session:
                session.add(invalid)

    with sessions.begin() as session:
        session.add(
            UserPolicy(
                user_id=owner, country_id="us", legacy_policy_id=1, client_ref="rf-1"
            )
        )
    with pytest.raises(IntegrityError):
        with sessions.begin() as session:
            session.add(
                UserPolicy(
                    user_id=owner,
                    country_id="us",
                    legacy_policy_id=2,
                    client_ref="rf-1",
                )
            )


def test_account_deletion_cascades_after_removing_legacy_mappings(sessions) -> None:
    alice = _principal(sessions, "google-oauth2|alice")
    bob = _principal(sessions, "google-oauth2|bob")
    deleted_subjects: list[str] = []
    service = V2AccountService(
        AccountDatabaseSession(sessions),
        legacy_references=default_legacy_references(),
        auth0_user_deleter=deleted_subjects.append,
    )
    alice_id = service.get_account(principal=alice, country_id="us").id
    bob_id = service.get_account(principal=bob, country_id="us").id
    service.import_records(
        principal=alice,
        country_id="us",
        import_input=AccountImportInput.model_validate(
            {
                "policies": [{"client_ref": "rf-1", "legacy_policy_id": 1}],
                "reports": [
                    {
                        "client_ref": "lfr-1",
                        "legacy_report_id": 615,
                        "user_policy_client_ref": "rf-1",
                    }
                ],
            }
        ),
    )
    with sessions.begin() as session:
        session.add(
            LegacyUserMapping(legacy_user_id=f"legacy-{uuid4().hex}", user_id=alice_id)
        )

    service.delete_account(principal=alice)

    assert deleted_subjects == [alice.subject]
    with sessions() as session:
        assert session.get(User, alice_id) is None
        assert session.get(User, bob_id) is not None
        for model in (LegacyUserMapping, UserPolicy, UserReportAssociation):
            assert (
                session.execute(
                    select(func.count())
                    .select_from(model)
                    .where(model.user_id == alice_id)
                ).scalar_one()
                == 0
            )


def test_qualification_reads_counts_in_a_read_only_transaction(sessions) -> None:
    disposable_url = _disposable_url()
    # The settings loader requires a persistent-looking target; the engine
    # builder substitutes the disposable database, which is all that is read.
    environ = {
        V2_MIGRATION_DATABASE_URL: (
            "postgresql+psycopg://migration:unused@db.abcdefghijklmnopqrst."
            "supabase.co/postgres?sslmode=require"
        ),
        V2_SUPABASE_PROJECT_REF: "abcdefghijklmnopqrst",
        V2_SUPABASE_ENVIRONMENT: "test",
    }
    observed_read_only: list[object] = []

    def pending_checker(connection) -> bool:
        observed_read_only.append(connection.connection.dbapi_connection.read_only)
        return user_association_migration_qualification.user_association_migration_is_pending(
            connection
        )

    evidence = (
        user_association_migration_qualification.qualify_user_association_migration(
            environ,
            engine_builder=lambda _settings: create_engine(disposable_url),
            pending_checker=pending_checker,
        )
    )

    assert observed_read_only == [True]
    assert evidence.migration_pending is False
    assert set(evidence.as_dict()["counts"]) == {
        "user_policies",
        "user_household_associations",
        "user_simulation_associations",
        "user_report_associations",
    }
