"""Service tests for unauthenticated users and their conversion at sign-in."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import logging
from uuid import UUID

import pytest
from sqlmodel import select

from policyengine_api.data.v2.models import (
    User,
    UserHouseholdAssociation,
    UserIdentity,
    UserPolicy,
    UserReportAssociation,
    UserSimulationAssociation,
)
from policyengine_api.services.v2.identity import services as identity_services
from policyengine_api.services.v2.identity.services import (
    StandardAccountProvisioning,
    UnauthenticatedAccountProvisioning,
    account_provisioning_for,
    find_principal_user_in_session,
    resolve_principal_user_for_read_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import (
    AccountConversionOutcome,
    UnauthenticatedPrincipal,
)
from policyengine_api.services.v2.identity.validators import (
    StandardUserRequiresSignInError,
)
from policyengine_api.services.v2.user_accounts import services as account_services
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_accounts.types import AccountUpdateInput
from policyengine_api.services.v2.user_accounts.validators import (
    AccountEditRequiresSignInError,
    AccountNotFoundError,
)
from policyengine_api.services.v2.user_households.database_session import (
    UserHouseholdDatabaseSession,
)
from policyengine_api.services.v2.user_households.services import (
    V2UserHouseholdService,
)
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreateFields,
)
from policyengine_api.services.v2.user_households.validators import (
    UserHouseholdNotFoundError,
)
from policyengine_api.services.v2.user_policies.database_session import (
    UserPolicyDatabaseSession,
)
from policyengine_api.services.v2.user_policies.services import V2UserPolicyService
from policyengine_api.services.v2.user_policies.types import (
    UserPolicyCreateFields,
    UserPolicyUpdateInput,
)
from policyengine_api.services.v2.user_policies.validators import (
    UserPolicyNotFoundError,
)
from policyengine_api.services.v2.user_reports.database_session import (
    UserReportDatabaseSession,
)
from policyengine_api.services.v2.user_reports.services import V2UserReportService
from policyengine_api.services.v2.user_reports.types import UserReportCreateFields
from policyengine_api.services.v2.user_reports.validators import (
    UserReportNotFoundError,
)
from policyengine_api.services.v2.user_simulations.database_session import (
    UserSimulationDatabaseSession,
)
from policyengine_api.services.v2.user_simulations.services import (
    V2UserSimulationService,
)
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
)
from policyengine_api.services.v2.user_simulations.validators import (
    UserSimulationNotFoundError,
)
from tests.unit.v2.user_service_support import (
    ALICE,
    BOB,
    OTHER_SIGNED_OUT_BROWSER,
    SIGNED_OUT_BROWSER,
    V2Store,
    default_legacy_references,
    v2_store,
)


BROWSER_USER_ID = SIGNED_OUT_BROWSER.user_id


@dataclass(frozen=True)
class Services:
    store: V2Store
    accounts: V2AccountService
    policies: V2UserPolicyService
    households: V2UserHouseholdService
    simulations: V2UserSimulationService
    reports: V2UserReportService


def _never_build_the_auth0_deleter():
    raise AssertionError("unauthenticated users have no Auth0 user")


@pytest.fixture
def services() -> Iterator[Services]:
    with v2_store() as store:
        references = default_legacy_references()
        yield Services(
            store=store,
            accounts=V2AccountService(
                AccountDatabaseSession(store.sessions),
                auth0_user_deleter_factory=_never_build_the_auth0_deleter,
            ),
            policies=V2UserPolicyService(
                UserPolicyDatabaseSession(store.sessions), references
            ),
            households=V2UserHouseholdService(
                UserHouseholdDatabaseSession(store.sessions), references
            ),
            simulations=V2UserSimulationService(
                UserSimulationDatabaseSession(store.sessions), references
            ),
            reports=V2UserReportService(
                UserReportDatabaseSession(store.sessions), references
            ),
        )


@dataclass(frozen=True)
class SavedRecords:
    policy_id: UUID
    household_id: UUID
    simulation_id: UUID
    report_id: UUID


def _save_one_of_each(services: Services, principal) -> SavedRecords:
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
            country_id="us", legacy_report_id=615, user_policy_id=policy.id
        ),
    )
    return SavedRecords(
        policy_id=policy.id,
        household_id=household.id,
        simulation_id=simulation.id,
        report_id=report.id,
    )


def _owners(services: Services, records: SavedRecords) -> dict[str, UUID | None]:
    with services.store.sessions() as session:
        rows = {
            "policy": session.get(UserPolicy, records.policy_id),
            "household": session.get(UserHouseholdAssociation, records.household_id),
            "simulation": session.get(UserSimulationAssociation, records.simulation_id),
            "report": session.get(UserReportAssociation, records.report_id),
        }
    return {kind: None if row is None else row.user_id for kind, row in rows.items()}


def _users(services: Services) -> list[User]:
    with services.store.sessions() as session:
        return list(session.exec(select(User)).all())


@contextmanager
def _recorded_logs(*loggers: logging.Logger) -> Iterator[list[logging.LogRecord]]:
    """Record INFO logs; Alembic tests may have disabled these loggers."""

    records: list[logging.LogRecord] = []

    class RecordingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = RecordingHandler(level=logging.INFO)
    previous = [(logger.disabled, logger.level) for logger in loggers]
    for logger in loggers:
        logger.disabled = False
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
    try:
        yield records
    finally:
        for logger, (was_disabled, level) in zip(loggers, previous, strict=True):
            logger.removeHandler(handler)
            logger.disabled = was_disabled
            logger.setLevel(level)


def _logged_text(records: list[logging.LogRecord]) -> str:
    return " ".join(
        f"{record.getMessage()} {getattr(record, 'policyengine_attributes', {})}"
        for record in records
    )


def test_the_selector_picks_a_strategy_from_the_principal_type() -> None:
    assert isinstance(account_provisioning_for(ALICE), StandardAccountProvisioning)
    assert isinstance(
        account_provisioning_for(SIGNED_OUT_BROWSER),
        UnauthenticatedAccountProvisioning,
    )


def test_the_browser_uuid_stays_out_of_principal_and_owner_reprs(
    services: Services,
) -> None:
    with services.store.sessions.begin() as session:
        owner = resolve_principal_user_in_session(
            session, SIGNED_OUT_BROWSER, country_id="us"
        )

    assert str(BROWSER_USER_ID) not in repr(SIGNED_OUT_BROWSER)
    assert str(BROWSER_USER_ID) not in repr(owner)


def test_writes_provision_an_unauthenticated_user_with_only_its_id(
    services: Services,
) -> None:
    with services.store.sessions.begin() as session:
        assert find_principal_user_in_session(session, SIGNED_OUT_BROWSER) is None
        first = resolve_principal_user_in_session(
            session, SIGNED_OUT_BROWSER, country_id="uk"
        )
    with services.store.sessions.begin() as session:
        second = resolve_principal_user_in_session(
            session, SIGNED_OUT_BROWSER, country_id="us"
        )
        found = find_principal_user_in_session(session, SIGNED_OUT_BROWSER)

    assert first == second == found
    assert (first.user_id, first.email, first.user_type) == (
        BROWSER_USER_ID,
        None,
        "unauthenticated",
    )
    (user,) = _users(services)
    assert (user.id, user.user_type) == (BROWSER_USER_ID, "unauthenticated")
    assert (
        user.primary_country,
        user.first_name,
        user.last_name,
        user.email,
    ) == (None, None, None, None)
    assert user.created_at is not None


def test_provisioning_retries_when_the_user_vanishes_before_the_re_read(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = identity_services.read_user
    reads = {"count": 0}

    def read_after_a_concurrent_deletion(session, user_id, **options):
        reads["count"] += 1
        if reads["count"] == 1:
            return None
        return original(session, user_id, **options)

    monkeypatch.setattr(
        identity_services, "read_user", read_after_a_concurrent_deletion
    )
    with services.store.sessions.begin() as session:
        owner = resolve_principal_user_in_session(
            session, SIGNED_OUT_BROWSER, country_id="us"
        )

    assert owner.user_id == BROWSER_USER_ID
    assert reads["count"] == 2


def test_standard_users_are_never_found_or_provisioned_through_the_header(
    services: Services,
) -> None:
    alice = services.accounts.get_account(principal=ALICE, country_id="us")
    impostor = UnauthenticatedPrincipal(user_id=alice.id)

    with services.store.sessions.begin() as session:
        with pytest.raises(StandardUserRequiresSignInError):
            find_principal_user_in_session(session, impostor)
        with pytest.raises(StandardUserRequiresSignInError):
            resolve_principal_user_in_session(session, impostor, country_id="us")
        with pytest.raises(StandardUserRequiresSignInError):
            resolve_principal_user_for_read_in_session(
                session, impostor, country_id="us"
            )
    for operation in (
        lambda: services.policies.list_user_policies(
            principal=impostor, country_id="us"
        ),
        lambda: services.policies.create_user_policy(
            principal=impostor,
            association_input=UserPolicyCreateFields(
                country_id="us", legacy_policy_id=1
            ),
        ),
        lambda: services.accounts.export_account(principal=impostor, country_id="us"),
        lambda: services.accounts.delete_account(principal=impostor),
    ):
        with pytest.raises(StandardUserRequiresSignInError):
            operation()

    (user,) = _users(services)
    assert (user.id, user.user_type) == (alice.id, "standard")
    with services.store.sessions() as session:
        assert session.exec(select(UserPolicy)).all() == []


def test_reads_never_provision_an_unauthenticated_user(services: Services) -> None:
    missing_id = UUID("00000000-0000-0000-0000-000000000123")
    pages = [
        services.policies.list_user_policies(
            principal=SIGNED_OUT_BROWSER, country_id="us"
        ),
        services.households.list_user_households(
            principal=SIGNED_OUT_BROWSER, country_id="us"
        ),
        services.simulations.list_user_simulations(
            principal=SIGNED_OUT_BROWSER, country_id="us"
        ),
        services.reports.list_user_reports(
            principal=SIGNED_OUT_BROWSER, country_id="us"
        ),
    ]
    for read, error in (
        (services.policies.get_user_policy, UserPolicyNotFoundError),
        (services.households.get_user_household, UserHouseholdNotFoundError),
        (services.simulations.get_user_simulation, UserSimulationNotFoundError),
        (services.reports.get_user_report, UserReportNotFoundError),
    ):
        with pytest.raises(error):
            read(
                principal=SIGNED_OUT_BROWSER,
                country_id="us",
                association_id=missing_id,
            )
    with pytest.raises(AccountNotFoundError) as not_found:
        services.accounts.get_account(principal=SIGNED_OUT_BROWSER, country_id="us")
    exported = services.accounts.export_account(
        principal=SIGNED_OUT_BROWSER, country_id="us"
    )

    assert all(page.items == () and not page.has_more for page in pages)
    assert str(BROWSER_USER_ID) not in str(not_found.value)
    assert exported.user is None
    assert (
        exported.policies,
        exported.households,
        exported.simulations,
        exported.reports,
    ) == ((), (), (), ())
    assert _users(services) == []


def test_unauthenticated_users_own_their_writes_and_read_them_back(
    services: Services,
) -> None:
    records = _save_one_of_each(services, SIGNED_OUT_BROWSER)

    account = services.accounts.get_account(
        principal=SIGNED_OUT_BROWSER, country_id="us"
    )
    exported = services.accounts.export_account(
        principal=SIGNED_OUT_BROWSER, country_id="us"
    )
    listed = services.policies.list_user_policies(
        principal=SIGNED_OUT_BROWSER, country_id="us"
    )
    renamed = services.policies.patch_user_policy(
        principal=SIGNED_OUT_BROWSER,
        country_id="us",
        association_id=records.policy_id,
        association_input=UserPolicyUpdateInput(name="Renamed"),
    )

    assert (account.id, account.user_type, account.primary_country) == (
        BROWSER_USER_ID,
        "unauthenticated",
        None,
    )
    assert exported.user == account
    assert [item.id for item in exported.reports] == [records.report_id]
    assert exported.reports[0].user_policy_id == records.policy_id
    assert [item.id for item in listed.items] == [records.policy_id]
    assert renamed.name == "Renamed"
    assert set(_owners(services, records).values()) == {BROWSER_USER_ID}
    with pytest.raises(UserPolicyNotFoundError):
        services.policies.get_user_policy(
            principal=OTHER_SIGNED_OUT_BROWSER,
            country_id="us",
            association_id=records.policy_id,
        )
    with pytest.raises(UserPolicyNotFoundError):
        services.policies.get_user_policy(
            principal=ALICE, country_id="us", association_id=records.policy_id
        )


def test_unauthenticated_users_cannot_edit_account_details(
    services: Services,
) -> None:
    for principal_state in ("absent", "present"):
        if principal_state == "present":
            _save_one_of_each(services, SIGNED_OUT_BROWSER)
        with pytest.raises(AccountEditRequiresSignInError):
            services.accounts.update_account(
                principal=SIGNED_OUT_BROWSER,
                country_id="us",
                account_input=AccountUpdateInput(first_name="Ada"),
            )

    (user,) = _users(services)
    assert user.first_name is None


def test_deleting_an_unauthenticated_account_removes_only_its_data(
    services: Services,
) -> None:
    absent = services.accounts.delete_account(principal=SIGNED_OUT_BROWSER)
    records = _save_one_of_each(services, SIGNED_OUT_BROWSER)
    other_records = _save_one_of_each(services, OTHER_SIGNED_OUT_BROWSER)

    deleted = services.accounts.delete_account(principal=SIGNED_OUT_BROWSER)

    assert (absent.user_id, absent.auth0_subjects) == (None, ())
    assert (deleted.user_id, deleted.auth0_subjects) == (BROWSER_USER_ID, ())
    assert set(_owners(services, records).values()) == {None}
    assert set(_owners(services, other_records).values()) == {
        OTHER_SIGNED_OUT_BROWSER.user_id
    }
    assert [user.id for user in _users(services)] == [OTHER_SIGNED_OUT_BROWSER.user_id]


def test_upgrade_converts_an_unauthenticated_user_in_place(
    services: Services,
) -> None:
    records = _save_one_of_each(services, SIGNED_OUT_BROWSER)

    upgrade = services.accounts.upgrade_account(
        principal=ALICE, unauthenticated_user_id=BROWSER_USER_ID, country_id="uk"
    )

    assert upgrade.outcome is AccountConversionOutcome.CONVERTED
    assert (
        upgrade.account.id,
        upgrade.account.user_type,
        upgrade.account.primary_country,
    ) == (BROWSER_USER_ID, "standard", "uk")
    assert set(_owners(services, records).values()) == {BROWSER_USER_ID}
    with services.store.sessions() as session:
        identity = session.exec(select(UserIdentity)).one()
        report = session.get(UserReportAssociation, records.report_id)
    assert (identity.user_id, identity.subject) == (BROWSER_USER_ID, ALICE.subject)
    assert report is not None and report.user_policy_id == records.policy_id
    signed_in = services.accounts.get_account(principal=ALICE, country_id="us")
    assert signed_in.id == BROWSER_USER_ID
    with pytest.raises(StandardUserRequiresSignInError):
        services.policies.list_user_policies(
            principal=SIGNED_OUT_BROWSER, country_id="us"
        )

    again = services.accounts.upgrade_account(
        principal=ALICE, unauthenticated_user_id=BROWSER_USER_ID, country_id="us"
    )
    assert again.outcome is AccountConversionOutcome.NONE
    assert again.account.id == BROWSER_USER_ID
    assert again.account.primary_country == "uk"


def test_upgrade_merges_every_association_into_an_existing_account(
    services: Services,
) -> None:
    alice = services.accounts.get_account(principal=ALICE, country_id="us")
    alice_records = _save_one_of_each(services, ALICE)
    records = _save_one_of_each(services, SIGNED_OUT_BROWSER)
    with services.store.sessions() as session:
        updated_before = {
            row.id: row.updated_at for row in session.exec(select(UserPolicy)).all()
        }

    upgrade = services.accounts.upgrade_account(
        principal=ALICE, unauthenticated_user_id=BROWSER_USER_ID, country_id="us"
    )

    assert upgrade.outcome is AccountConversionOutcome.MERGED
    assert (upgrade.account.id, upgrade.account.user_type) == (alice.id, "standard")
    assert set(_owners(services, records).values()) == {alice.id}
    assert set(_owners(services, alice_records).values()) == {alice.id}
    assert [user.id for user in _users(services)] == [alice.id]
    with services.store.sessions() as session:
        report = session.get(UserReportAssociation, records.report_id)
        updated_after = {
            row.id: row.updated_at for row in session.exec(select(UserPolicy)).all()
        }
    assert report is not None and report.user_policy_id == records.policy_id
    assert updated_after == updated_before
    linked = services.reports.get_user_report(
        principal=ALICE, country_id="us", association_id=records.report_id
    )
    assert linked.user_policy_id == records.policy_id
    with pytest.raises(AccountNotFoundError):
        services.accounts.get_account(principal=SIGNED_OUT_BROWSER, country_id="us")


def test_upgrade_without_an_unauthenticated_user_resolves_the_account(
    services: Services,
) -> None:
    upgrade = services.accounts.upgrade_account(
        principal=ALICE, unauthenticated_user_id=BROWSER_USER_ID, country_id="uk"
    )

    assert upgrade.outcome is AccountConversionOutcome.NONE
    assert upgrade.account.id != BROWSER_USER_ID
    assert (upgrade.account.user_type, upgrade.account.primary_country) == (
        "standard",
        "uk",
    )
    assert [user.id for user in _users(services)] == [upgrade.account.id]


def test_upgrade_never_touches_a_standard_user_named_by_the_header(
    services: Services,
) -> None:
    bob = services.accounts.get_account(principal=BOB, country_id="us")
    bob_records = _save_one_of_each(services, BOB)

    upgrade = services.accounts.upgrade_account(
        principal=ALICE, unauthenticated_user_id=bob.id, country_id="us"
    )

    assert upgrade.outcome is AccountConversionOutcome.NONE
    assert upgrade.account.id != bob.id
    assert set(_owners(services, bob_records).values()) == {bob.id}
    with services.store.sessions() as session:
        identities = {
            identity.subject: identity.user_id
            for identity in session.exec(select(UserIdentity)).all()
        }
    assert identities == {BOB.subject: bob.id, ALICE.subject: upgrade.account.id}


def test_upgrade_merges_when_a_concurrent_first_sign_in_wins_the_identity(
    services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = _save_one_of_each(services, SIGNED_OUT_BROWSER)
    original = identity_services.create_user_identity
    winner: dict[str, UUID] = {}

    def lose_to_a_concurrent_first_request(session, **identity):
        # SQLite has one in-memory connection, so the winning request's rows
        # are written through this session; the insert below then conflicts.
        user = User(primary_country="us")
        session.add(user)
        session.flush()
        session.add(
            UserIdentity(
                user_id=user.id,
                issuer=identity["issuer"],
                subject=identity["subject"],
            )
        )
        session.flush()
        winner["user_id"] = user.id
        return original(session, **identity)

    monkeypatch.setattr(
        identity_services,
        "create_user_identity",
        lose_to_a_concurrent_first_request,
    )

    upgrade = services.accounts.upgrade_account(
        principal=ALICE, unauthenticated_user_id=BROWSER_USER_ID, country_id="us"
    )

    assert upgrade.outcome is AccountConversionOutcome.MERGED
    assert upgrade.account.id == winner["user_id"]
    assert set(_owners(services, records).values()) == {winner["user_id"]}
    assert [user.id for user in _users(services)] == [winner["user_id"]]


def test_unauthenticated_user_ids_are_never_logged(services: Services) -> None:
    with _recorded_logs(identity_services.logger, account_services.logger) as records:
        _save_one_of_each(services, SIGNED_OUT_BROWSER)
        services.accounts.delete_account(principal=SIGNED_OUT_BROWSER)
        _save_one_of_each(services, SIGNED_OUT_BROWSER)
        services.accounts.upgrade_account(
            principal=ALICE, unauthenticated_user_id=BROWSER_USER_ID, country_id="us"
        )

    events = [
        (record.getMessage(), record.policyengine_attributes) for record in records
    ]
    assert events == [
        ("provisioned_v2_user", {"user_type": "unauthenticated"}),
        ("deleted_v2_user_account", {"user_type": "unauthenticated"}),
        ("provisioned_v2_user", {"user_type": "unauthenticated"}),
        ("upgraded_v2_user", {"outcome": "converted"}),
    ]
    assert str(BROWSER_USER_ID) not in _logged_text(records)
    assert BROWSER_USER_ID.hex not in _logged_text(records)
