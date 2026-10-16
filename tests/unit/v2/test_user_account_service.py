"""Service tests for signed-in identity provisioning, saves, and deletion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    User,
    UserIdentity,
    UserPolicy,
    UserSimulationAssociation,
)
from policyengine_api.services.v2.associations.validators import (
    AssociationLinkNotFoundError,
)
from policyengine_api.services.v2.identity import services as identity_services
from policyengine_api.services.v2.identity.services import (
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_accounts.types import AccountUpdateInput
from policyengine_api.services.v2.user_accounts.validators import (
    AccountDeletionUnavailableError,
    AccountIdentityDeletionError,
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
from policyengine_api.services.v2.user_reports.types import (
    SharedBaselineReformRead,
    UserReportCreateFields,
    UserReportUpdateInput,
)
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
    UserSimulationUpdateInput,
)
from policyengine_api.services.v2.user_simulations.validators import (
    UserSimulationNotFoundError,
)
from tests.unit.v2.user_service_support import (
    ALICE,
    BOB,
    ISSUER,
    default_legacy_references,
    v2_store,
)


@pytest.fixture
def store():
    with v2_store() as selected:
        yield selected


class RecordingAuth0Deleter:
    """Record Auth0 calls; optionally fail preparation or deletion."""

    def __init__(
        self,
        *,
        prepare_error: Exception | None = None,
        delete_error: Exception | None = None,
        on_prepare=None,
    ) -> None:
        self.prepare_error = prepare_error
        self.delete_error = delete_error
        self.on_prepare = on_prepare
        self.prepared = 0
        self.deleted_subjects: list[str] = []

    def prepare_deletion(self) -> None:
        self.prepared += 1
        if self.on_prepare is not None:
            self.on_prepare()
        if self.prepare_error is not None:
            raise self.prepare_error

    def delete_user(self, subject: str) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted_subjects.append(subject)


def _services(selected, *, deleter=None, deleter_factory=None):
    references = default_legacy_references()
    if deleter_factory is None and deleter is not None:

        def deleter_factory():
            return deleter

    return (
        V2AccountService(
            AccountDatabaseSession(selected.sessions),
            auth0_user_deleter_factory=deleter_factory,
        ),
        V2UserPolicyService(UserPolicyDatabaseSession(selected.sessions), references),
        V2UserSimulationService(
            UserSimulationDatabaseSession(selected.sessions), references
        ),
        V2UserReportService(UserReportDatabaseSession(selected.sessions), references),
    )


def test_first_call_provisions_once_and_later_calls_reuse_the_user(store) -> None:
    accounts, *_ = _services(store)

    first = accounts.get_account(principal=ALICE, country_id="uk")
    second = accounts.get_account(principal=ALICE, country_id="us")
    other = accounts.get_account(principal=BOB, country_id="us")

    assert first.id == second.id != other.id
    assert first.primary_country == second.primary_country == "uk"
    with store.sessions() as session:
        assert len(session.exec(select(User)).all()) == 2
        assert len(session.exec(select(UserIdentity)).all()) == 2


def test_concurrent_first_calls_converge_on_one_user(store, monkeypatch) -> None:
    original = identity_services.read_user_identity
    reads = {"count": 0}

    def racing_read(session, **identity):
        reads["count"] += 1
        if reads["count"] == 1:
            with store.sessions.begin() as winner:
                user = User(primary_country="us")
                winner.add(user)
                winner.flush()
                winner.add(UserIdentity(user_id=user.id, **identity))
            return None
        return original(session, **identity)

    monkeypatch.setattr(identity_services, "read_user_identity", racing_read)
    accounts, *_ = _services(store)

    resolved = accounts.get_account(principal=ALICE, country_id="us")

    with store.sessions() as session:
        users = session.exec(select(User)).all()
        identities = session.exec(select(UserIdentity)).all()
    assert [user.id for user in users] == [resolved.id]
    assert [identity.user_id for identity in identities] == [resolved.id]


def test_identity_activity_is_written_at_most_hourly(store) -> None:
    now = datetime(2026, 5, 1, 12, tzinfo=UTC)
    verified = UserPrincipal(issuer=ISSUER, subject=ALICE.subject, email="a@x.test")

    def resolve(principal, at):
        with store.sessions.begin() as session:
            resolve_principal_user_in_session(
                session, principal, country_id="us", now=at
            )
        with store.sessions() as session:
            identity = session.exec(select(UserIdentity)).one()
            return identity.last_seen_at.replace(tzinfo=UTC), identity.email

    assert resolve(ALICE, now) == (now, None)
    assert resolve(ALICE, now + timedelta(minutes=59)) == (now, None)
    assert resolve(ALICE, now + timedelta(minutes=61)) == (
        now + timedelta(minutes=61),
        None,
    )
    assert resolve(verified, now + timedelta(minutes=62)) == (
        now + timedelta(minutes=62),
        "a@x.test",
    )
    assert resolve(ALICE, now + timedelta(minutes=63)) == (
        now + timedelta(minutes=62),
        "a@x.test",
    )


def test_account_updates_names_and_country(store) -> None:
    accounts, *_ = _services(store)

    updated = accounts.update_account(
        principal=ALICE,
        country_id="us",
        account_input=AccountUpdateInput(first_name="Ada", primary_country="uk"),
    )

    assert (updated.first_name, updated.last_name, updated.primary_country) == (
        "Ada",
        None,
        "uk",
    )


def test_simulation_saves_are_owner_scoped_and_v1_checked(store) -> None:
    _accounts, _policies, simulations, _reports = _services(store)
    created = simulations.create_user_simulation(
        principal=ALICE,
        association_input=UserSimulationCreateFields(
            country_id="us", legacy_simulation_id=613
        ),
    )

    with pytest.raises(LegacyReferenceNotFoundError):
        simulations.create_user_simulation(
            principal=ALICE,
            association_input=UserSimulationCreateFields(
                country_id="us", legacy_simulation_id=999
            ),
        )
    with pytest.raises(UserSimulationNotFoundError):
        simulations.patch_user_simulation(
            principal=BOB,
            country_id="us",
            association_id=created.id,
            association_input=UserSimulationUpdateInput(name="stolen"),
        )
    repointed = simulations.patch_user_simulation(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserSimulationUpdateInput(legacy_simulation_id=614),
    )
    assert (repointed.simulation_id, repointed.legacy_simulation_id) == (None, 614)
    assert [
        item.id
        for item in simulations.list_user_simulations(
            principal=ALICE, country_id="us", legacy_simulation_id=614
        ).items
    ] == [created.id]


def test_report_policy_links_require_the_same_owner_and_survive_deletion(
    store,
) -> None:
    _accounts, policies, _simulations, reports = _services(store)
    alice_policy = policies.create_user_policy(
        principal=ALICE,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )
    bob_policy = policies.create_user_policy(
        principal=BOB,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=2),
    )

    report = reports.create_user_report(
        principal=ALICE,
        association_input=UserReportCreateFields.model_validate(
            {
                "country_id": "us",
                "legacy_report_id": 615,
                "user_policy_id": str(alice_policy.id),
                "provisions": [
                    {
                        "path": "gov.x",
                        "breadcrumb": "X",
                        "baseline_value": 1,
                        "value": 2,
                    }
                ],
            }
        ),
    )
    with pytest.raises(AssociationLinkNotFoundError):
        reports.create_user_report(
            principal=ALICE,
            association_input=UserReportCreateFields(
                country_id="us", legacy_report_id=615, user_policy_id=bob_policy.id
            ),
        )
    with pytest.raises(AssociationLinkNotFoundError):
        reports.patch_user_report(
            principal=ALICE,
            country_id="us",
            association_id=report.id,
            association_input=UserReportUpdateInput(user_policy_id=bob_policy.id),
        )

    with pytest.raises(AssociationLinkNotFoundError):
        reports.create_user_report(
            principal=ALICE,
            association_input=UserReportCreateFields(
                country_id="us",
                legacy_report_id=615,
                baseline_user_policy_id=bob_policy.id,
            ),
        )
    with pytest.raises(AssociationLinkNotFoundError):
        reports.patch_user_report(
            principal=ALICE,
            country_id="us",
            association_id=report.id,
            association_input=UserReportUpdateInput(
                baseline_user_policy_id=bob_policy.id
            ),
        )
    compared = reports.patch_user_report(
        principal=ALICE,
        country_id="us",
        association_id=report.id,
        association_input=UserReportUpdateInput(
            baseline_user_policy_id=alice_policy.id
        ),
    )
    assert compared.baseline_user_policy_id == alice_policy.id

    assert report.user_policy_id == alice_policy.id
    assert report.provisions == [
        {"path": "gov.x", "breadcrumb": "X", "baseline_value": 1, "value": 2}
    ]
    policies.delete_user_policy(
        principal=ALICE, country_id="us", association_id=alice_policy.id
    )
    refreshed = reports.get_user_report(
        principal=ALICE, country_id="us", association_id=report.id
    )
    assert refreshed.user_policy_id is None


def test_anyone_reads_a_saved_report_by_its_link_without_the_owner(store) -> None:
    _accounts, policies, _simulations, reports = _services(store)
    compared = policies.create_user_policy(
        principal=ALICE,
        association_input=UserPolicyCreateFields(
            country_id="us", legacy_policy_id=1, name="Current plan"
        ),
    )
    report = reports.create_user_report(
        principal=ALICE,
        association_input=UserReportCreateFields.model_validate(
            {
                "country_id": "us",
                "legacy_report_id": 615,
                "name": "CTC report",
                "source_note": "from chat",
                "user_policy_id": str(compared.id),
                "baseline_user_policy_id": str(compared.id),
                "budget_window_years": 10,
                "provisions": [
                    {
                        "path": "gov.x",
                        "breadcrumb": "X",
                        "baseline_value": 1,
                        "value": 2,
                    }
                ],
            }
        ),
    )

    # No principal: the report's ID is the link.
    shared = reports.get_shared_user_report(country_id="us", association_id=report.id)

    assert (shared.id, shared.legacy_report_id, shared.name, shared.source_note) == (
        report.id,
        615,
        "CTC report",
        "from chat",
    )
    assert shared.provisions == report.provisions
    assert shared.budget_window_years == 10
    assert shared.baseline_reform == SharedBaselineReformRead(name="Current plan")
    for private_field in ("user_id", "user_policy_id", "baseline_user_policy_id"):
        assert not hasattr(shared, private_field)
    with pytest.raises(UserReportNotFoundError):
        reports.get_shared_user_report(country_id="uk", association_id=report.id)

    policies.delete_user_policy(
        principal=ALICE, country_id="us", association_id=compared.id
    )
    assert (
        reports.get_shared_user_report(
            country_id="us", association_id=report.id
        ).baseline_reform
        is None
    )


def test_export_covers_every_country(store) -> None:
    accounts, policies, *_ = _services(store)
    policies.create_user_policy(
        principal=ALICE,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )
    policies.create_user_policy(
        principal=ALICE,
        association_input=UserPolicyCreateFields(country_id="uk", legacy_policy_id=7),
    )
    policies.create_user_policy(
        principal=BOB,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=2),
    )

    exported = accounts.export_account(principal=ALICE, country_id="us")

    assert sorted(item.country_id for item in exported.policies) == ["uk", "us"]
    assert exported.households == exported.simulations == exported.reports == ()


def test_delete_removes_legacy_mappings_identities_and_associations(store) -> None:
    deleter = RecordingAuth0Deleter()
    accounts, policies, simulations, _reports = _services(store, deleter=deleter)
    account = accounts.get_account(principal=ALICE, country_id="us")
    policies.create_user_policy(
        principal=ALICE,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )
    simulations.create_user_simulation(
        principal=ALICE,
        association_input=UserSimulationCreateFields(
            country_id="us", legacy_simulation_id=613
        ),
    )
    accounts.get_account(principal=BOB, country_id="us")
    with store.sessions.begin() as session:
        session.add(
            LegacyUserMapping(legacy_user_id="auth0|legacy", user_id=account.id)
        )
        session.add(
            UserIdentity(
                user_id=account.id, issuer=ISSUER, subject="google-oauth2|alice-linked"
            )
        )

    deletion = accounts.delete_account(principal=ALICE)

    assert deletion.user_id == account.id
    assert deleter.prepared == 1
    assert deleter.deleted_subjects == [ALICE.subject, "google-oauth2|alice-linked"]
    with store.sessions() as session:
        assert session.get(User, account.id) is None
        assert session.exec(select(LegacyUserMapping)).all() == []
        assert {
            identity.subject for identity in session.exec(select(UserIdentity))
        } == {BOB.subject}
        assert session.exec(select(UserPolicy)).all() == []
        assert session.exec(select(UserSimulationAssociation)).all() == []


def test_delete_without_management_api_or_with_failures(store) -> None:
    accounts, *_ = _services(store)
    accounts.get_account(principal=ALICE, country_id="us")

    assert accounts.delete_account(principal=ALICE).auth0_subjects == ()
    assert accounts.delete_account(principal=ALICE).user_id is None

    failing_deleter = RecordingAuth0Deleter(
        delete_error=RuntimeError("management api down")
    )
    failing, *_ = _services(store, deleter=failing_deleter)
    failing.get_account(principal=BOB, country_id="us")
    with pytest.raises(AccountIdentityDeletionError):
        failing.delete_account(principal=BOB)
    with store.sessions() as session:
        assert session.exec(select(User)).all() == []


def test_reads_lists_and_account_routes_never_build_the_v1_checker(store) -> None:
    from policyengine_api.services.v2.legacy_refs.services import (
        DeferredLegacyReferenceService,
    )

    def unavailable():
        msg = "the v1 reference service must not be built"
        raise AssertionError(msg)

    references = DeferredLegacyReferenceService(unavailable)
    accounts = V2AccountService(AccountDatabaseSession(store.sessions))
    simulations = V2UserSimulationService(
        UserSimulationDatabaseSession(store.sessions), references
    )

    accounts.get_account(principal=ALICE, country_id="us")
    accounts.export_account(principal=ALICE, country_id="us")
    page = simulations.list_user_simulations(principal=ALICE, country_id="us")

    assert page.items == ()
    with pytest.raises(AssertionError, match="must not be built"):
        simulations.create_user_simulation(
            principal=ALICE,
            association_input=UserSimulationCreateFields(
                country_id="us", legacy_simulation_id=613
            ),
        )


@pytest.mark.parametrize("failure", ["settings", "credentials"])
def test_auth0_credential_failures_stop_deletion_before_any_data_changes(
    store, failure
) -> None:
    def unusable_settings():
        msg = "AUTH0_MANAGEMENT_DOMAIN must be a bare host name"
        raise RuntimeError(msg)

    if failure == "settings":
        accounts, *_ = _services(store, deleter_factory=unusable_settings)
    else:
        accounts, *_ = _services(
            store,
            deleter=RecordingAuth0Deleter(
                prepare_error=RuntimeError("secret access denied")
            ),
        )
    account = accounts.get_account(principal=ALICE, country_id="us")

    with pytest.raises(AccountDeletionUnavailableError, match="nothing was deleted"):
        accounts.delete_account(principal=ALICE)

    with store.sessions() as session:
        assert session.get(User, account.id) is not None
        assert session.exec(select(UserIdentity)).all() != []


def test_auth0_credentials_are_prepared_before_data_is_deleted(store) -> None:
    accounts_for_lookup, *_ = _services(store)
    account = accounts_for_lookup.get_account(principal=ALICE, country_id="us")
    user_present_at_prepare: list[bool] = []

    def record_user_presence() -> None:
        with store.sessions() as session:
            user_present_at_prepare.append(session.get(User, account.id) is not None)

    deleter = RecordingAuth0Deleter(on_prepare=record_user_presence)
    accounts, *_ = _services(store, deleter=deleter)

    accounts.delete_account(principal=ALICE)

    assert user_present_at_prepare == [True]
    assert deleter.deleted_subjects == [ALICE.subject]


def test_only_account_deletion_builds_the_auth0_deleter(store) -> None:
    def unexpected_build():
        msg = "the Auth0 deleter must be built only for deletion"
        raise AssertionError(msg)

    accounts, *_ = _services(store, deleter_factory=unexpected_build)

    accounts.get_account(principal=ALICE, country_id="us")
    accounts.update_account(
        principal=ALICE,
        country_id="us",
        account_input=AccountUpdateInput(first_name="Ada"),
    )
    accounts.export_account(principal=ALICE, country_id="us")
