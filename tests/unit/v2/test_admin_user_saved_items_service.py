"""Service tests for admins reading a signed-in user's saved items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest

from policyengine_api import observability
from policyengine_api.data.v2.models import User, UserType
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
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
from policyengine_api.services.v2.user_types.database_session import (
    UserTypeDatabaseSession,
)
from policyengine_api.services.v2.user_types.services import V2UserTypeService
from policyengine_api.services.v2.user_types.validators import (
    SignedInUserNotFoundError,
    UserTypeBelowMinimumError,
)
from tests.unit.v2.user_service_support import (
    ALICE,
    BOB,
    ISSUER,
    SIGNED_OUT_BROWSER,
    V2Store,
    default_legacy_references,
    v2_store,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

BOB_WITH_EMAIL = UserPrincipal(
    issuer=ISSUER, subject=BOB.subject, email="bob@example.test"
)
CAROL = UserPrincipal(issuer=ISSUER, subject="google-oauth2|carol")
NEVER_SEEN = UserPrincipal(issuer=ISSUER, subject="google-oauth2|never-seen")
ABSENT_USER_ID = UUID("00000000-0000-0000-0000-0000000000a1")


class RecordedEvents:
    """Stands in for the observability runtime, keeping every event it records."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def event(
        self,
        name: str,
        *,
        severity: str = "INFO",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.events.append((name, severity, dict(attributes or {})))


@dataclass(frozen=True)
class Services:
    store: V2Store
    accounts: V2AccountService
    user_types: V2UserTypeService
    policies: V2UserPolicyService
    households: V2UserHouseholdService
    simulations: V2UserSimulationService
    reports: V2UserReportService


def _never_build_the_auth0_deleter():
    msg = "these tests delete no account"
    raise AssertionError(msg)


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
            user_types=V2UserTypeService(UserTypeDatabaseSession(store.sessions)),
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


@pytest.fixture
def recorded_events(monkeypatch: pytest.MonkeyPatch) -> RecordedEvents:
    recorder = RecordedEvents()
    monkeypatch.setattr(observability, "get_runtime", lambda: recorder)
    return recorder


def _sign_in(services: Services, principal: UserPrincipal) -> UUID:
    return services.accounts.get_account(principal=principal, country_id="us").id


def _store_type(services: Services, user_id: UUID, user_type: UserType) -> None:
    with services.store.sessions.begin() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.user_type = user_type.value


def _signed_in_admin(services: Services, principal: UserPrincipal) -> UUID:
    user_id = _sign_in(services, principal)
    _store_type(services, user_id, UserType.ADMIN)
    return user_id


def _save_one_of_each(services: Services, principal) -> None:
    """Save two policies, in two countries, and a household, simulation and report."""
    policy = services.policies.create_user_policy(
        principal=principal,
        association_input=UserPolicyCreateFields(country_id="us", legacy_policy_id=1),
    )
    services.policies.create_user_policy(
        principal=principal,
        association_input=UserPolicyCreateFields(country_id="uk", legacy_policy_id=7),
    )
    services.households.create_user_household(
        principal=principal,
        association_input=UserHouseholdCreateFields(
            country_id="us", legacy_household_id=10
        ),
    )
    services.simulations.create_user_simulation(
        principal=principal,
        association_input=UserSimulationCreateFields(
            country_id="us", legacy_simulation_id=613
        ),
    )
    services.reports.create_user_report(
        principal=principal,
        association_input=UserReportCreateFields(
            country_id="us", legacy_report_id=615, user_policy_id=policy.id
        ),
    )


def test_an_admin_reads_what_the_users_own_export_holds_and_the_read_is_recorded(
    services: Services, recorded_events: RecordedEvents
) -> None:
    alice_id = _signed_in_admin(services, ALICE)
    bob_id = _sign_in(services, BOB_WITH_EMAIL)
    _save_one_of_each(services, BOB_WITH_EMAIL)
    _save_one_of_each(services, CAROL)

    saved_items = services.user_types.get_user_saved_items(
        principal=ALICE, user_id=bob_id
    )
    own_export = services.accounts.export_account(
        principal=BOB_WITH_EMAIL, country_id="uk"
    )

    assert saved_items == own_export
    assert saved_items.user is not None
    assert (saved_items.user.id, saved_items.user.email) == (
        bob_id,
        "bob@example.test",
    )
    assert sorted(item.country_id for item in saved_items.policies) == ["uk", "us"]
    assert [
        len(saved_items.households),
        len(saved_items.simulations),
        len(saved_items.reports),
    ] == [1, 1, 1]
    assert {
        item.user_id
        for item in (
            *saved_items.policies,
            *saved_items.households,
            *saved_items.simulations,
            *saved_items.reports,
        )
    } == {bob_id}
    # Only the two users' IDs are recorded, never what the user saved.
    assert recorded_events.events == [
        (
            "admin_read_v2_user_saved_items",
            "INFO",
            {"admin_v2_user_id": str(alice_id), "v2_user_id": str(bob_id)},
        )
    ]


def test_only_admins_read_a_users_saved_items(
    services: Services, recorded_events: RecordedEvents
) -> None:
    _sign_in(services, ALICE)
    bob_id = _sign_in(services, BOB)
    _store_type(services, bob_id, UserType.AUTHOR)
    _save_one_of_each(services, BOB)
    _save_one_of_each(services, SIGNED_OUT_BROWSER)

    # A standard user, an author reading its own items, a signed-in caller with
    # no user yet, and a signed-out browser with saved work.
    for principal in (ALICE, BOB, NEVER_SEEN, SIGNED_OUT_BROWSER):
        with pytest.raises(UserTypeBelowMinimumError):
            services.user_types.get_user_saved_items(
                principal=principal, user_id=bob_id
            )
    assert recorded_events.events == []


def test_an_unauthenticated_or_absent_users_saved_items_are_not_found(
    services: Services, recorded_events: RecordedEvents
) -> None:
    _signed_in_admin(services, ALICE)
    _save_one_of_each(services, SIGNED_OUT_BROWSER)

    for user_id in (SIGNED_OUT_BROWSER.user_id, ABSENT_USER_ID):
        with pytest.raises(SignedInUserNotFoundError) as refused:
            services.user_types.get_user_saved_items(principal=ALICE, user_id=user_id)
        assert str(user_id) not in str(refused.value)
    # The browser's ID is its credential, so nothing about it is recorded.
    assert recorded_events.events == []
