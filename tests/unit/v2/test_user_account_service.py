"""Service tests for identity provisioning, saves, imports, and deletion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from policyengine_api.data.v2.models import (
    LegacyUserMapping,
    User,
    UserHouseholdAssociation,
    UserIdentity,
    UserPolicy,
    UserReportAssociation,
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
from policyengine_api.services.v2.user_accounts.types import (
    AccountImportInput,
    AccountUpdateInput,
)
from policyengine_api.services.v2.user_accounts.validators import (
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
    UserReportCreateFields,
    UserReportUpdateInput,
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
    MAPPED_LEGACY_POLICY_ID,
    default_legacy_references,
    v2_store,
)


@pytest.fixture
def store():
    with v2_store() as selected:
        yield selected


def _services(selected, *, deleter=None):
    references = default_legacy_references()
    return (
        V2AccountService(
            AccountDatabaseSession(selected.sessions),
            legacy_references=references,
            auth0_user_deleter=deleter,
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
    now = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
    verified = UserPrincipal(issuer=ISSUER, subject=ALICE.subject, email="a@x.test")

    def resolve(principal, at):
        with store.sessions.begin() as session:
            resolve_principal_user_in_session(
                session, principal, country_id="us", now=at
            )
        with store.sessions() as session:
            identity = session.exec(select(UserIdentity)).one()
            return identity.last_seen_at.replace(tzinfo=timezone.utc), identity.email

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
            country_id="us", legacy_simulation_id=613, client_ref="sus-1"
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


def _import_input(**sections) -> AccountImportInput:
    return AccountImportInput.model_validate(sections)


def test_import_is_idempotent_and_skips_unknown_or_invalid_items(store) -> None:
    accounts, *_ = _services(store)
    request = _import_input(
        policies=[
            {"client_ref": "rf-1", "legacy_policy_id": MAPPED_LEGACY_POLICY_ID},
            {"client_ref": "sup-404", "legacy_policy_id": 404},
            {"client_ref": "sup-bad", "legacy_policy_id": "1"},
        ],
        households=[{"client_ref": "suh-1", "legacy_household_id": 10}],
        simulations=[{"client_ref": "sus-1", "legacy_simulation_id": 613}],
        reports=[
            {
                "client_ref": "lfr-1",
                "legacy_report_id": 615,
                "user_policy_client_ref": "rf-1",
                "source_note": "imported",
            },
            {"legacy_report_id": 615},
        ],
    )

    first = accounts.import_records(
        principal=ALICE, country_id="us", import_input=request
    )
    second = accounts.import_records(
        principal=ALICE, country_id="us", import_input=request
    )

    assert set(first.id_map) == {"rf-1", "suh-1", "sus-1", "lfr-1"}
    assert first.id_map == second.id_map
    assert [(skip.client_ref, skip.reason.value) for skip in first.skipped] == [
        ("sup-bad", "invalid"),
        ("sup-404", "unknown_legacy_reference"),
        (None, "invalid"),
    ]
    with store.sessions() as session:
        policy = session.get(UserPolicy, first.id_map["rf-1"])
        report = session.get(UserReportAssociation, first.id_map["lfr-1"])
        assert policy is not None and policy.policy_id == store.policy_id
        assert report is not None and report.user_policy_id == policy.id
        assert len(session.exec(select(UserPolicy)).all()) == 1
        assert len(session.exec(select(UserHouseholdAssociation)).all()) == 1
        assert len(session.exec(select(UserSimulationAssociation)).all()) == 1


def test_import_keeps_existing_rows_and_links_earlier_imported_policies(
    store,
) -> None:
    accounts, *_ = _services(store)
    accounts.import_records(
        principal=ALICE,
        country_id="us",
        import_input=_import_input(
            policies=[{"client_ref": "rf-1", "legacy_policy_id": 1, "name": "First"}]
        ),
    )

    result = accounts.import_records(
        principal=ALICE,
        country_id="us",
        import_input=_import_input(
            policies=[{"client_ref": "rf-1", "legacy_policy_id": 2, "name": "Second"}],
            reports=[
                {
                    "client_ref": "lfr-2",
                    "legacy_report_id": 616,
                    "user_policy_client_ref": "rf-1",
                },
                {
                    "client_ref": "lfr-3",
                    "legacy_report_id": 616,
                    "user_policy_client_ref": "rf-unknown",
                },
            ],
        ),
    )

    with store.sessions() as session:
        policy = session.get(UserPolicy, result.id_map["rf-1"])
        linked = session.get(UserReportAssociation, result.id_map["lfr-2"])
        unlinked = session.get(UserReportAssociation, result.id_map["lfr-3"])
    assert (policy.name, policy.legacy_policy_id) == ("First", 1)
    assert linked.user_policy_id == policy.id
    assert unlinked.user_policy_id is None


def test_import_input_bounds_the_item_count() -> None:
    with pytest.raises(ValueError, match="at most 500"):
        _import_input(
            policies=[{"client_ref": str(index)} for index in range(250)],
            reports=[{"client_ref": str(index)} for index in range(251)],
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
    deleted_subjects: list[str] = []
    accounts, policies, simulations, _reports = _services(
        store, deleter=deleted_subjects.append
    )
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
    assert deleted_subjects == [ALICE.subject, "google-oauth2|alice-linked"]
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

    def failing_deleter(_subject: str) -> None:
        raise RuntimeError("management api down")

    failing, *_ = _services(store, deleter=failing_deleter)
    failing.get_account(principal=BOB, country_id="us")
    with pytest.raises(AccountIdentityDeletionError):
        failing.delete_account(principal=BOB)
    with store.sessions() as session:
        assert session.exec(select(User)).all() == []
