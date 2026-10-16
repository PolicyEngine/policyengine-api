"""PostgreSQL tests for identity provisioning, unauthenticated users, and upgrades.

These prove the behaviors SQLite cannot: named ``ON CONFLICT`` targets,
concurrent first sign-in, concurrent first writes by one signed-out browser,
row locks that serialize conversion at sign-in with that browser's writes,
``MATCH SIMPLE`` composite keys with NULL references, and cascading account
deletion.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.data.v2 import user_association_migration_qualification
from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    User,
    UserHouseholdAssociation,
    UserIdentity,
    UserPolicy,
    UserReportAssociation,
    UserSimulationAssociation,
)
from policyengine_api.data.v2.settings import (
    V2_MIGRATION_DATABASE_URL,
    V2_SUPABASE_ENVIRONMENT,
    V2_SUPABASE_PROJECT_REF,
)
from policyengine_api.services.v2.identity.services import (
    convert_unauthenticated_user_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import (
    AccountConversionOutcome,
    UnauthenticatedPrincipal,
    UserPrincipal,
)
from policyengine_api.services.v2.identity.validators import (
    StandardUserRequiresSignInError,
)
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_accounts.types import AccountUpdateInput
from policyengine_api.services.v2.user_households.database_session import (
    UserHouseholdDatabaseSession,
)
from policyengine_api.services.v2.user_households.services import (
    V2UserHouseholdService,
)
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreateFields,
)
from policyengine_api.services.v2.user_policies.database_session import (
    UserPolicyDatabaseSession,
)
from policyengine_api.services.v2.user_policies.services import V2UserPolicyService
from policyengine_api.services.v2.user_policies.types import UserPolicyCreateFields
from policyengine_api.services.v2.user_reports.database_session import (
    UserReportDatabaseSession,
)
from policyengine_api.services.v2.user_reports.services import V2UserReportService
from policyengine_api.services.v2.user_reports.types import UserReportCreateFields
from policyengine_api.services.v2.user_simulations.database_session import (
    UserSimulationDatabaseSession,
)
from policyengine_api.services.v2.user_simulations.services import (
    V2UserSimulationService,
)
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
)
from tests.unit.v2.user_service_support import default_legacy_references

if TYPE_CHECKING:
    from collections.abc import Iterator

# Long enough for a write that is not blocked by a held row lock to finish.
LOCK_WAIT_SECONDS = 1.0
ASSOCIATION_MODELS = (
    UserPolicy,
    UserHouseholdAssociation,
    UserSimulationAssociation,
    UserReportAssociation,
)


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
    factory.kw["info"] = {"issuer": issuer, "browser_user_ids": []}
    try:
        yield factory
    finally:
        with engine.begin() as connection:
            owned = select(UserIdentity.user_id).where(UserIdentity.issuer == issuer)
            user_ids = [
                *connection.execute(owned).scalars(),
                *factory.kw["info"]["browser_user_ids"],
            ]
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


def _browser(sessions) -> UnauthenticatedPrincipal:
    """Return a fresh signed-out browser whose user the fixture removes afterwards."""
    user_id = uuid4()
    sessions.kw["info"]["browser_user_ids"].append(user_id)
    return UnauthenticatedPrincipal(user_id=user_id)


def _count(sessions, statement) -> int:
    with sessions() as session:
        return int(session.execute(statement).scalar_one())


@dataclass(frozen=True)
class Services:
    accounts: V2AccountService
    policies: V2UserPolicyService
    households: V2UserHouseholdService
    simulations: V2UserSimulationService
    reports: V2UserReportService


def _services(sessions) -> Services:
    references = default_legacy_references()
    return Services(
        accounts=V2AccountService(AccountDatabaseSession(sessions)),
        policies=V2UserPolicyService(UserPolicyDatabaseSession(sessions), references),
        households=V2UserHouseholdService(
            UserHouseholdDatabaseSession(sessions), references
        ),
        simulations=V2UserSimulationService(
            UserSimulationDatabaseSession(sessions), references
        ),
        reports=V2UserReportService(UserReportDatabaseSession(sessions), references),
    )


def _save_one_of_each(services: Services, principal) -> dict[type, UUID]:
    policy = services.policies.create_user_policy(
        principal=principal,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )
    household = services.households.create_user_household(
        principal=principal,
        association_input=UserHouseholdCreateFields(
            country_id="us", legacy_household_id=10
        ),
    )
    simulation = services.simulations.create_user_simulation(
        principal=principal,
        association_input=UserSimulationCreateFields(
            country_id="us", legacy_simulation_id=613
        ),
    )
    report = services.reports.create_user_report(
        principal=principal,
        association_input=UserReportCreateFields(
            country_id="us",
            legacy_report_id=615,
            user_policy_id=policy.id,
            baseline_user_policy_id=policy.id,
        ),
    )
    return {
        UserPolicy: policy.id,
        UserHouseholdAssociation: household.id,
        UserSimulationAssociation: simulation.id,
        UserReportAssociation: report.id,
    }


def _owners(sessions, records: dict[type, UUID]) -> set[UUID | None]:
    with sessions() as session:
        return {
            None if row is None else row.user_id
            for row in (
                session.get(model, record_id) for model, record_id in records.items()
            )
        }


def _save_policy(services: Services, principal) -> UUID:
    return services.policies.create_user_policy(
        principal=principal,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    ).id


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


def test_concurrent_first_writes_by_one_browser_create_exactly_one_user(
    sessions,
) -> None:
    browser = _browser(sessions)
    services = _services(sessions)
    workers = 8
    barrier = Barrier(workers)

    def first_write(_index: int) -> UUID:
        barrier.wait()
        return services.policies.create_user_policy(
            principal=browser,
            association_input=UserPolicyCreateFields(
                country_id="us", legacy_policy_id=1
            ),
        ).user_id

    with ThreadPoolExecutor(max_workers=workers) as executor:
        owners = set(executor.map(first_write, range(workers)))

    assert owners == {browser.user_id}
    with sessions() as session:
        user = session.get(User, browser.user_id)
        policy_count = session.execute(
            select(func.count())
            .select_from(UserPolicy)
            .where(UserPolicy.user_id == browser.user_id)
        ).scalar_one()
    assert user is not None
    assert (user.user_type, user.primary_country, user.email) == (
        "unauthenticated",
        None,
        None,
    )
    assert policy_count == workers


def test_concurrent_upgrades_of_one_browser_convert_exactly_once(sessions) -> None:
    browser = _browser(sessions)
    alice = _principal(sessions, "google-oauth2|converted-once")
    services = _services(sessions)
    records = _save_one_of_each(services, browser)
    workers = 6
    barrier = Barrier(workers)

    def upgrade(_index: int):
        barrier.wait()
        return services.accounts.upgrade_account(
            principal=alice,
            unauthenticated_user_id=browser.user_id,
            country_id="us",
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        upgrades = list(executor.map(upgrade, range(workers)))

    assert sorted(upgrade.outcome.value for upgrade in upgrades) == [
        "converted",
        *["none"] * (workers - 1),
    ]
    assert {upgrade.account.id for upgrade in upgrades} == {browser.user_id}
    assert _owners(sessions, records) == {browser.user_id}
    with sessions() as session:
        identities = session.execute(
            select(UserIdentity.user_id).where(UserIdentity.issuer == alice.issuer)
        ).all()
        user = session.get(User, browser.user_id)
    assert [row.user_id for row in identities] == [browser.user_id]
    assert user is not None and user.user_type == "standard"


def test_concurrent_first_upgrades_from_two_browsers_share_one_account(
    sessions,
) -> None:
    browsers = [_browser(sessions), _browser(sessions)]
    alice = _principal(sessions, "google-oauth2|two-browsers")
    services = _services(sessions)
    records = [_save_one_of_each(services, browser) for browser in browsers]
    barrier = Barrier(len(browsers))

    def upgrade(browser: UnauthenticatedPrincipal):
        barrier.wait()
        return services.accounts.upgrade_account(
            principal=alice,
            unauthenticated_user_id=browser.user_id,
            country_id="us",
        )

    with ThreadPoolExecutor(max_workers=len(browsers)) as executor:
        upgrades = list(executor.map(upgrade, browsers))

    # The first sign-in converts one browser in place; the other loses the
    # UNIQUE(issuer, subject) race and merges into it.
    assert sorted(upgrade.outcome.value for upgrade in upgrades) == [
        "converted",
        "merged",
    ]
    (account_id,) = {upgrade.account.id for upgrade in upgrades}
    assert account_id in {browser.user_id for browser in browsers}
    assert all(_owners(sessions, saved) == {account_id} for saved in records)
    remaining = _count(
        sessions,
        select(func.count())
        .select_from(User)
        .where(User.id.in_([browser.user_id for browser in browsers])),
    )
    assert remaining == 1


def test_merge_moves_every_association_and_keeps_links_and_constraints(
    sessions,
) -> None:
    browser = _browser(sessions)
    alice = _principal(sessions, "google-oauth2|merged")
    services = _services(sessions)
    alice_id = services.accounts.get_account(principal=alice, country_id="us").id
    alice_records = _save_one_of_each(services, alice)
    browser_records = _save_one_of_each(services, browser)

    upgrade = services.accounts.upgrade_account(
        principal=alice, unauthenticated_user_id=browser.user_id, country_id="us"
    )

    assert upgrade.outcome is AccountConversionOutcome.MERGED
    assert upgrade.account.id == alice_id
    assert _owners(sessions, browser_records) == {alice_id}
    assert _owners(sessions, alice_records) == {alice_id}
    with sessions() as session:
        assert session.get(User, browser.user_id) is None
        report = session.get(
            UserReportAssociation, browser_records[UserReportAssociation]
        )
    assert report is not None
    assert report.user_policy_id == browser_records[UserPolicy]
    assert report.baseline_user_policy_id == browser_records[UserPolicy]
    exported = services.accounts.export_account(principal=alice, country_id="us")
    assert len(exported.policies) == len(exported.reports) == 2

    # The moved report's link still follows its policy's ON DELETE SET NULL.
    services.policies.delete_user_policy(
        principal=alice,
        country_id="us",
        association_id=browser_records[UserPolicy],
    )
    linked = services.reports.get_user_report(
        principal=alice,
        country_id="us",
        association_id=browser_records[UserReportAssociation],
    )
    assert linked.user_policy_id is None
    assert linked.baseline_user_policy_id is None


def _hold_a_conversion(sessions, *, browser, principal) -> Session:
    """Convert or merge ``browser`` in an open transaction holding its lock."""
    session = sessions()
    session.begin()
    convert_unauthenticated_user_in_session(
        session,
        unauthenticated_user_id=browser.user_id,
        principal=principal,
        country_id="us",
    )
    return session


def test_a_browser_write_waits_for_its_conversion_and_is_then_refused(
    sessions,
) -> None:
    browser = _browser(sessions)
    alice = _principal(sessions, "google-oauth2|write-during-conversion")
    services = _services(sessions)
    _save_policy(services, browser)
    converting = _hold_a_conversion(sessions, browser=browser, principal=alice)

    with ThreadPoolExecutor(max_workers=1) as executor:
        write = executor.submit(_save_policy, services, browser)
        time.sleep(LOCK_WAIT_SECONDS)
        assert not write.done()
        converting.commit()
        converting.close()
        with pytest.raises(StandardUserRequiresSignInError):
            write.result(timeout=30)

    with sessions() as session:
        policy_count = session.execute(
            select(func.count())
            .select_from(UserPolicy)
            .where(UserPolicy.user_id == browser.user_id)
        ).scalar_one()
    assert policy_count == 1


def test_a_browser_write_after_its_merge_starts_a_new_unauthenticated_user(
    sessions,
) -> None:
    browser = _browser(sessions)
    alice = _principal(sessions, "google-oauth2|write-during-merge")
    services = _services(sessions)
    alice_id = services.accounts.get_account(principal=alice, country_id="us").id
    merged_policy_id = _save_policy(services, browser)
    merging = _hold_a_conversion(sessions, browser=browser, principal=alice)

    with ThreadPoolExecutor(max_workers=1) as executor:
        write = executor.submit(_save_policy, services, browser)
        time.sleep(LOCK_WAIT_SECONDS)
        assert not write.done()
        merging.commit()
        merging.close()
        new_policy_id = write.result(timeout=30)

    with sessions() as session:
        merged_policy = session.get(UserPolicy, merged_policy_id)
        new_policy = session.get(UserPolicy, new_policy_id)
        browser_user = session.get(User, browser.user_id)
    assert merged_policy is not None and merged_policy.user_id == alice_id
    assert new_policy is not None and new_policy.user_id == browser.user_id
    assert browser_user is not None and browser_user.user_type == "unauthenticated"


def test_a_browser_account_deletion_never_deletes_its_converted_user(
    sessions,
) -> None:
    browser = _browser(sessions)
    alice = _principal(sessions, "google-oauth2|delete-during-conversion")
    services = _services(sessions)
    policy_id = _save_policy(services, browser)
    converting = _hold_a_conversion(sessions, browser=browser, principal=alice)

    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(services.accounts.delete_account, principal=browser)
        time.sleep(LOCK_WAIT_SECONDS)
        assert not deletion.done()
        converting.commit()
        converting.close()
        deletion.result(timeout=30)

    with sessions() as session:
        user = session.get(User, browser.user_id)
        policy = session.get(UserPolicy, policy_id)
    assert user is not None and user.user_type == "standard"
    assert policy is not None and policy.user_id == browser.user_id


def test_upgrade_never_locks_a_standard_user_named_by_the_header(sessions) -> None:
    alice = _principal(sessions, "google-oauth2|names-someone-else")
    bob = _principal(sessions, "google-oauth2|named-by-the-header")
    services = _services(sessions)
    bob_id = services.accounts.get_account(principal=bob, country_id="us").id
    upgrading = sessions()
    upgrading.begin()
    try:
        conversion = convert_unauthenticated_user_in_session(
            upgrading,
            unauthenticated_user_id=bob_id,
            principal=alice,
            country_id="us",
        )
        assert conversion.outcome is AccountConversionOutcome.NONE
        # Bob's own account update would wait here if his row were locked.
        with ThreadPoolExecutor(max_workers=1) as executor:
            update = executor.submit(
                services.accounts.update_account,
                principal=bob,
                country_id="us",
                account_input=AccountUpdateInput(first_name="Bob"),
            )
            assert update.result(timeout=10 * LOCK_WAIT_SECONDS).first_name == "Bob"
    finally:
        upgrading.rollback()
        upgrading.close()


def test_unauthenticated_users_are_written_only_with_their_id(sessions) -> None:
    browser = _browser(sessions)
    alice = _principal(sessions, "google-oauth2|not-a-browser")
    services = _services(sessions)
    alice_id = services.accounts.get_account(principal=alice, country_id="us").id

    page = services.policies.list_user_policies(principal=browser, country_id="us")
    with pytest.raises(StandardUserRequiresSignInError):
        services.policies.list_user_policies(
            principal=UnauthenticatedPrincipal(user_id=alice_id), country_id="us"
        )
    _save_policy(services, browser)

    assert page.items == ()
    with sessions() as session:
        user = session.get(User, browser.user_id)
    assert user is not None
    assert (
        user.user_type,
        user.primary_country,
        user.first_name,
        user.last_name,
        user.email,
    ) == ("unauthenticated", None, None, None, None)
    with pytest.raises(IntegrityError):
        with sessions.begin() as session:
            session.add(User(user_type="standard"))


def test_non_finite_numbers_never_reach_jsonb(sessions) -> None:
    principal = _principal(sessions, "google-oauth2|non-finite")
    services = _services(sessions)
    provision = {
        "path": "gov.irs.credits.ctc.amount",
        "breadcrumb": "Child Tax Credit amount",
        "baseline_value": 2000,
        "value": 3000,
    }

    stored = services.reports.create_user_report(
        principal=principal,
        association_input=UserReportCreateFields.model_validate(
            {"country_id": "us", "legacy_report_id": 615, "provisions": [provision]}
        ),
    )
    with pytest.raises(ValidationError):
        UserReportCreateFields.model_validate(
            {
                "country_id": "us",
                "legacy_report_id": 616,
                "provisions": [{**provision, "value": float("inf")}],
            }
        )

    with sessions() as session:
        row = session.get(UserReportAssociation, stored.id)
    assert row is not None and row.provisions == [provision]


def test_report_budget_windows_persist_within_the_api_window_limit(sessions) -> None:
    principal = _principal(sessions, "google-oauth2|budget-window")
    services = _services(sessions)

    stored = services.reports.create_user_report(
        principal=principal,
        association_input=UserReportCreateFields(
            country_id="us", legacy_report_id=615, budget_window_years=10
        ),
    )
    with sessions() as session:
        row = session.get(UserReportAssociation, stored.id)
    assert row is not None and row.budget_window_years == 10

    for out_of_range_years in (1, 76):
        with pytest.raises(IntegrityError):
            with sessions.begin() as session:
                session.add(
                    UserReportAssociation(
                        user_id=stored.user_id,
                        country_id="us",
                        legacy_report_id=615,
                        budget_window_years=out_of_range_years,
                    )
                )


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
                # One owner may save the same v1 policy more than once.
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


def test_account_deletion_cascades_after_removing_legacy_mappings(sessions) -> None:
    alice = _principal(sessions, "google-oauth2|alice")
    bob = _principal(sessions, "google-oauth2|bob")
    deleted_subjects: list[str] = []

    class RecordingDeleter:
        def prepare_deletion(self) -> None:
            return None

        def delete_user(self, subject: str) -> None:
            deleted_subjects.append(subject)

    services = _services(sessions)
    accounts = V2AccountService(
        AccountDatabaseSession(sessions),
        auth0_user_deleter_factory=RecordingDeleter,
    )
    alice_id = accounts.get_account(principal=alice, country_id="us").id
    bob_id = accounts.get_account(principal=bob, country_id="us").id
    _save_one_of_each(services, alice)
    with sessions.begin() as session:
        session.add(
            LegacyUserMapping(legacy_user_id=f"legacy-{uuid4().hex}", user_id=alice_id)
        )

    accounts.delete_account(principal=alice)

    assert deleted_subjects == [alice.subject]
    with sessions() as session:
        assert session.get(User, alice_id) is None
        assert session.get(User, bob_id) is not None
        for model in (LegacyUserMapping, *ASSOCIATION_MODELS):
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
