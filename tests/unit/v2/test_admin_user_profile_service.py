"""Service tests for admins' reads of users' emails and names from Auth0.

The admin user routes read each signed-in user's email and names from the
users' Auth0 tenant when an admin asks, and store nothing. A stand-in reader
plays Auth0 here; the Management API client itself is tested in
``tests/unit/libs/test_auth0_management.py``.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlmodel import select

from policyengine_api.data.v2.models import (
    User,
    UserIdentity,
    UserType,
    UserTypeChange,
)
from policyengine_api.libs.auth0_management import (
    Auth0ManagementConfigurationError,
    Auth0UserIdSearch,
    Auth0UserProfile,
    Auth0UserProfilesUnavailableError,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.user_accounts.database_session import (
    AccountDatabaseSession,
)
from policyengine_api.services.v2.user_accounts.services import V2AccountService
from policyengine_api.services.v2.user_types import services as user_type_services
from policyengine_api.services.v2.user_types.database_session import (
    UserTypeDatabaseSession,
)
from policyengine_api.services.v2.user_types.services import V2UserTypeService
from policyengine_api.services.v2.user_types.types import (
    AdminUserSearch,
    UserProfileSource,
)
from policyengine_api.services.v2.user_types.validators import (
    AdminUserProfilesUnavailableError,
    UserTypeBelowMinimumError,
)
from tests.unit.v2.user_service_support import ISSUER, V2Store, v2_store

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from uuid import UUID

OTHER_ISSUER = "https://other-tenant.example.test/"
FIRST_SEEN = datetime(2026, 1, 1, tzinfo=UTC)
LATER = datetime(2026, 3, 1, tzinfo=UTC)


class StandInProfileReader:
    """Answer profile reads and email searches as Auth0 would, recording each."""

    def __init__(
        self,
        profiles: Iterable[Auth0UserProfile] = (),
        *,
        email_matches: Iterable[str] = (),
        limit_reached: bool = False,
        failure: Exception | None = None,
    ) -> None:
        self.profiles = {profile.user_id: profile for profile in profiles}
        self.email_matches = tuple(email_matches)
        self.limit_reached = limit_reached
        self.failure = failure
        self.profile_reads: list[tuple[str, ...]] = []
        self.email_searches: list[str] = []

    def read_user_profiles(
        self, user_ids: Iterable[str]
    ) -> dict[str, Auth0UserProfile]:
        requested = tuple(user_ids)
        self.profile_reads.append(requested)
        if self.failure is not None:
            raise self.failure
        return {
            user_id: self.profiles[user_id]
            for user_id in requested
            if user_id in self.profiles
        }

    def search_user_ids_by_email(self, text: str) -> Auth0UserIdSearch:
        self.email_searches.append(text)
        if self.failure is not None:
            raise self.failure
        return Auth0UserIdSearch(
            user_ids=self.email_matches, limit_reached=self.limit_reached
        )


def _profile(subject: str, **fields: object) -> Auth0UserProfile:
    """Build an Auth0 profile with only the given fields set."""
    values: dict[str, object] = {
        "email": None,
        "email_verified": False,
        "given_name": None,
        "family_name": None,
        "name": None,
    }
    values.update(fields)
    return Auth0UserProfile(user_id=subject, **values)


@pytest.fixture
def store() -> Iterator[V2Store]:
    with v2_store() as isolated_store:
        yield isolated_store


def _principal(
    name: str, *, email: str | None = None, issuer: str = ISSUER
) -> UserPrincipal:
    return UserPrincipal(issuer=issuer, subject=f"google-oauth2|{name}", email=email)


def _sign_in(store: V2Store, principal: UserPrincipal, *, created_at: datetime) -> UUID:
    """Provision the principal's user, created at ``created_at``."""
    user_id = (
        V2AccountService(AccountDatabaseSession(store.sessions))
        .get_account(principal=principal, country_id="us")
        .id
    )
    with store.sessions.begin() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.created_at = created_at
        for identity in session.exec(
            select(UserIdentity).where(UserIdentity.user_id == user_id)
        ).all():
            identity.last_seen_at = created_at
    return user_id


def _add_identity(
    store: V2Store,
    user_id: UUID,
    subject: str,
    *,
    last_seen_at: datetime,
    issuer: str = ISSUER,
) -> None:
    with store.sessions.begin() as session:
        session.add(
            UserIdentity(
                user_id=user_id,
                issuer=issuer,
                subject=subject,
                last_seen_at=last_seen_at,
            )
        )


def _make_admin(store: V2Store, user_id: UUID) -> None:
    with store.sessions.begin() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.user_type = UserType.ADMIN.value


def _user_types(
    store: V2Store,
    reader: StandInProfileReader | None,
    *,
    source_factory: Callable[[], UserProfileSource | None] | None = None,
) -> V2UserTypeService:
    """Read profiles through ``reader``, unless ``source_factory`` is given."""

    def stand_in_source() -> UserProfileSource:
        assert reader is not None
        return UserProfileSource(issuer=ISSUER, reader=reader)

    return V2UserTypeService(
        UserTypeDatabaseSession(store.sessions),
        user_profile_source_factory=source_factory or stand_in_source,
    )


@contextmanager
def _recorded_logs() -> Iterator[list[logging.LogRecord]]:
    """Record the user-type service's logs, wherever logging is configured."""
    records: list[logging.LogRecord] = []

    class RecordingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    service_logger = user_type_services.logger
    handler = RecordingHandler(level=logging.INFO)
    previous_disabled, previous_level = service_logger.disabled, service_logger.level
    service_logger.disabled = False
    service_logger.setLevel(logging.INFO)
    service_logger.addHandler(handler)
    try:
        yield records
    finally:
        service_logger.removeHandler(handler)
        service_logger.disabled = previous_disabled
        service_logger.setLevel(previous_level)


def _logged_text(records: list[logging.LogRecord]) -> str:
    return " ".join(
        f"{record.getMessage()} {getattr(record, 'policyengine_attributes', {})}"
        for record in records
    )


def test_listed_users_take_emails_and_names_from_auth0(store: V2Store) -> None:
    alice = _principal("alice")
    alice_id = _sign_in(store, alice, created_at=FIRST_SEEN)
    _make_admin(store, alice_id)
    bob_id = _sign_in(
        store,
        _principal("bob", email="bob@stored.example.test"),
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    carol_id = _sign_in(
        store,
        _principal("carol", email="carol@stored.example.test"),
        created_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    dave_id = _sign_in(
        store, _principal("dave"), created_at=datetime(2026, 1, 4, tzinfo=UTC)
    )
    # Dave signed in with a second identity later; the users' issuer has both.
    _add_identity(store, dave_id, "auth0|dave-password", last_seen_at=LATER)
    reader = StandInProfileReader(
        [
            _profile(
                "google-oauth2|alice",
                email="alice@auth0.example.test",
                email_verified=True,
                given_name="Alice",
                family_name="Admin",
            ),
            # Only an unverified email, and a full name without its parts.
            _profile(
                "google-oauth2|bob",
                email="bob-unverified@auth0.example.test",
                name="Bob Builder",
            ),
            # The most recently seen identity's email is unverified, so the
            # older identity's verified one is preferred; names come from the
            # most recently seen identity that has any.
            _profile(
                "auth0|dave-password",
                email="dave-new@auth0.example.test",
                given_name="Dave",
            ),
            _profile(
                "google-oauth2|dave",
                email="dave@auth0.example.test",
                email_verified=True,
                given_name="David",
                family_name="Older",
            ),
        ]
    )

    page = _user_types(store, reader).list_users(
        principal=alice, search=AdminUserSearch()
    )

    assert [
        (user.id, user.email, user.first_name, user.last_name) for user in page.items
    ] == [
        (dave_id, "dave@auth0.example.test", "Dave", None),
        # Carol has no Auth0 profile, so her stored email stays.
        (carol_id, "carol@stored.example.test", None, None),
        (bob_id, "bob-unverified@auth0.example.test", "Bob Builder", None),
        (alice_id, "alice@auth0.example.test", "Alice", "Admin"),
    ]
    # One read for the whole page, newest user first, each user's most
    # recently seen identity first.
    assert reader.profile_reads == [
        (
            "auth0|dave-password",
            "google-oauth2|dave",
            "google-oauth2|carol",
            "google-oauth2|bob",
            "google-oauth2|alice",
        )
    ]
    with store.sessions() as session:
        stored_emails = {
            user.id: user.email for user in session.exec(select(User)).all()
        }
        identity_emails = {
            identity.subject: identity.email
            for identity in session.exec(select(UserIdentity)).all()
        }
    # Nothing read from Auth0 is stored.
    assert "alice@auth0.example.test" not in {
        *stored_emails.values(),
        *identity_emails.values(),
    }
    assert identity_emails["google-oauth2|bob"] == "bob@stored.example.test"


def test_a_stored_name_is_kept_and_a_full_name_that_is_an_email_is_not_used(
    store: V2Store,
) -> None:
    alice = _principal("alice")
    alice_id = _sign_in(store, alice, created_at=FIRST_SEEN)
    _make_admin(store, alice_id)
    with store.sessions.begin() as session:
        user = session.get(User, alice_id)
        assert user is not None
        user.first_name = "Stored"
        user.last_name = "Name"
    bob_id = _sign_in(store, _principal("bob"), created_at=LATER)
    reader = StandInProfileReader(
        [
            _profile("google-oauth2|alice", family_name="Auth0"),
            # Auth0 sets a database user's name to its email address.
            _profile(
                "google-oauth2|bob",
                email="bob@auth0.example.test",
                name="bob@auth0.example.test",
            ),
        ]
    )
    user_types = _user_types(store, reader)

    alice_read = user_types.get_user(principal=alice, user_id=alice_id)
    bob_read = user_types.get_user(principal=alice, user_id=bob_id)

    assert (alice_read.first_name, alice_read.last_name) == ("Stored", "Auth0")
    assert (bob_read.email, bob_read.first_name, bob_read.last_name) == (
        "bob@auth0.example.test",
        None,
        None,
    )


def test_identities_from_another_issuer_are_never_looked_up(store: V2Store) -> None:
    alice = _principal("alice")
    alice_id = _sign_in(store, alice, created_at=FIRST_SEEN)
    _make_admin(store, alice_id)
    other_tenant_user_id = _sign_in(
        store,
        _principal("erin", email="erin@stored.example.test", issuer=OTHER_ISSUER),
        created_at=LATER,
    )
    reader = StandInProfileReader(
        [_profile("google-oauth2|erin", email="erin@auth0.example.test")]
    )

    erin = _user_types(store, reader).get_user(
        principal=alice, user_id=other_tenant_user_id
    )

    assert erin.email == "erin@stored.example.test"
    assert reader.profile_reads == []


@pytest.mark.parametrize(
    "failure",
    [
        Auth0UserProfilesUnavailableError("Auth0 user profiles are unavailable"),
        RuntimeError("unexpected failure naming google-oauth2|bob"),
    ],
)
def test_unavailable_profiles_keep_stored_values_and_record_a_warning(
    store: V2Store, failure: Exception
) -> None:
    alice = _principal("alice")
    alice_id = _sign_in(store, alice, created_at=FIRST_SEEN)
    _make_admin(store, alice_id)
    bob_id = _sign_in(
        store, _principal("bob", email="bob@stored.example.test"), created_at=LATER
    )
    reader = StandInProfileReader(failure=failure)
    user_types = _user_types(store, reader)

    with _recorded_logs() as records:
        page = user_types.list_users(principal=alice, search=AdminUserSearch())
        bob = user_types.get_user(principal=alice, user_id=bob_id)
        changed = user_types.change_user_type(
            principal=alice,
            user_id=bob_id,
            user_type=UserType.AUTHOR,
            expected_user_type=UserType.STANDARD,
        )
        (change,) = user_types.list_user_type_changes(principal=alice, user_id=bob_id)

    assert [user.email for user in page.items] == ["bob@stored.example.test", None]
    assert bob.email == "bob@stored.example.test"
    assert (changed.user_type, changed.email) == (
        UserType.AUTHOR,
        "bob@stored.example.test",
    )
    # The admin's change was committed although its response used stored values.
    with store.sessions() as session:
        stored_bob = session.get(User, bob_id)
        assert stored_bob is not None
        assert stored_bob.user_type == "author"
        assert len(session.exec(select(UserTypeChange)).all()) == 1
    assert change.changed_by_user_id == alice_id
    assert change.changed_by_email is None
    assert [
        (record.levelno, record.getMessage(), record.policyengine_attributes)
        for record in records
    ] == [
        (
            logging.WARNING,
            "admin_user_profiles_unavailable",
            {"operation": "read_profiles", "error_type": type(failure).__name__},
        )
    ] * 4
    logged = _logged_text(records)
    for personal in ("google-oauth2|", "bob@", str(bob_id), "alice"):
        assert personal not in logged


def test_a_broken_profile_configuration_keeps_stored_values(store: V2Store) -> None:
    alice = _principal("alice", email="alice@stored.example.test")
    alice_id = _sign_in(store, alice, created_at=FIRST_SEEN)
    _make_admin(store, alice_id)

    def broken_configuration() -> UserProfileSource:
        msg = "Auth0 user profile reads are partially configured"
        raise Auth0ManagementConfigurationError(msg)

    user_types = _user_types(store, None, source_factory=broken_configuration)

    with _recorded_logs() as records:
        page = user_types.list_users(principal=alice, search=AdminUserSearch())
        with pytest.raises(AdminUserProfilesUnavailableError):
            user_types.list_users(
                principal=alice, search=AdminUserSearch(email="alice")
            )

    assert [user.email for user in page.items] == ["alice@stored.example.test"]
    assert [
        (record.getMessage(), record.policyengine_attributes) for record in records
    ] == [
        (
            "admin_user_profiles_unavailable",
            {
                "operation": "configure",
                "error_type": "Auth0ManagementConfigurationError",
            },
        )
    ] * 2


def _signed_in_people(store: V2Store) -> dict[str, UUID]:
    """Sign in Alice (an admin), then Bob, Carol, Dave and Erin, oldest first."""
    people = {}
    for day, name in enumerate(("alice", "bob", "carol", "dave", "erin"), start=1):
        email = "carol@builders.example.test" if name == "carol" else None
        people[name] = _sign_in(
            store,
            _principal(name, email=email),
            created_at=datetime(2026, 1, day, tzinfo=UTC),
        )
    _make_admin(store, people["alice"])
    return people


def test_an_email_search_finds_users_through_auth0_and_their_stored_emails(
    store: V2Store,
) -> None:
    people = _signed_in_people(store)
    # A user of another tenant with a matching subject is no match.
    other_tenant_user_id = _sign_in(
        store,
        _principal("bob", issuer=OTHER_ISSUER),
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    reader = StandInProfileReader(
        [
            _profile("google-oauth2|bob", email="bob@builders.example.test"),
            _profile("google-oauth2|erin", email="erin@builders.example.test"),
        ],
        email_matches=[
            "google-oauth2|bob",
            "google-oauth2|erin",
            "google-oauth2|never-signed-in",
        ],
    )
    user_types = _user_types(store, reader)
    alice = _principal("alice")

    first_page = user_types.list_users(
        principal=alice, search=AdminUserSearch(email="Builders", limit=2)
    )
    second_page = user_types.list_users(
        principal=alice, search=AdminUserSearch(email="Builders", offset=2, limit=2)
    )

    # Erin and Bob match in Auth0, and Carol by her stored email; newest first.
    assert [(user.id, user.email) for user in first_page.items] == [
        (people["erin"], "erin@builders.example.test"),
        (people["carol"], "carol@builders.example.test"),
    ]
    assert (first_page.offset, first_page.limit, first_page.has_more) == (0, 2, True)
    assert [(user.id, user.email) for user in second_page.items] == [
        (people["bob"], "bob@builders.example.test"),
    ]
    assert second_page.has_more is False
    assert other_tenant_user_id not in {
        user.id for user in (*first_page.items, *second_page.items)
    }
    assert reader.email_searches == ["Builders", "Builders"]


def test_an_email_search_answers_unavailable_when_auth0_fails(
    store: V2Store,
) -> None:
    _signed_in_people(store)
    reader = StandInProfileReader(
        failure=Auth0UserProfilesUnavailableError(
            "Auth0 user profiles are unavailable: HTTP 429"
        )
    )

    with _recorded_logs() as records, pytest.raises(AdminUserProfilesUnavailableError):
        _user_types(store, reader).list_users(
            principal=_principal("alice"),
            search=AdminUserSearch(email="carol@builders"),
        )

    assert [
        (record.levelno, record.getMessage(), record.policyengine_attributes)
        for record in records
    ] == [
        (
            logging.WARNING,
            "admin_user_profiles_unavailable",
            {
                "operation": "search_by_email",
                "error_type": "Auth0UserProfilesUnavailableError",
            },
        )
    ]
    assert "carol" not in _logged_text(records)
    assert reader.profile_reads == []


def test_an_email_search_at_auth0s_result_limit_answers_and_records_a_warning(
    store: V2Store,
) -> None:
    people = _signed_in_people(store)
    reader = StandInProfileReader(
        email_matches=["google-oauth2|dave"], limit_reached=True
    )

    with _recorded_logs() as records:
        page = _user_types(store, reader).list_users(
            principal=_principal("alice"), search=AdminUserSearch(email="example")
        )

    assert [user.id for user in page.items] == [people["dave"], people["carol"]]
    assert [
        (record.levelno, record.getMessage(), record.policyengine_attributes)
        for record in records
    ] == [
        (
            logging.WARNING,
            "admin_user_email_search_limit_reached",
            {"auth0_result_count": 1},
        )
    ]


def test_without_profile_settings_an_email_search_reads_only_stored_emails(
    store: V2Store,
) -> None:
    people = _signed_in_people(store)
    user_types = _user_types(store, None, source_factory=lambda: None)

    page = user_types.list_users(
        principal=_principal("alice"), search=AdminUserSearch(email="builders")
    )

    assert [(user.id, user.email) for user in page.items] == [
        (people["carol"], "carol@builders.example.test")
    ]


def test_callers_below_admin_never_reach_auth0(store: V2Store) -> None:
    people = _signed_in_people(store)
    bob = _principal("bob")
    reader = StandInProfileReader(email_matches=["google-oauth2|bob"])
    user_types = _user_types(store, reader)

    with pytest.raises(UserTypeBelowMinimumError):
        user_types.list_users(principal=bob, search=AdminUserSearch(email="bob"))
    with pytest.raises(UserTypeBelowMinimumError):
        user_types.list_users(principal=bob, search=AdminUserSearch())
    with pytest.raises(UserTypeBelowMinimumError):
        user_types.get_user(principal=bob, user_id=people["carol"])

    assert reader.email_searches == []
    assert reader.profile_reads == []


def test_a_changed_user_and_its_history_take_emails_from_auth0(
    store: V2Store,
) -> None:
    people = _signed_in_people(store)
    alice = _principal("alice")
    reader = StandInProfileReader(
        [
            _profile(
                "google-oauth2|alice",
                email="alice@auth0.example.test",
                email_verified=True,
            ),
            _profile(
                "google-oauth2|bob",
                email="bob@auth0.example.test",
                email_verified=True,
                given_name="Bob",
            ),
        ]
    )
    user_types = _user_types(store, reader)

    changed = user_types.change_user_type(
        principal=alice,
        user_id=people["bob"],
        user_type=UserType.AUTHOR,
        expected_user_type=UserType.STANDARD,
    )
    (change,) = user_types.list_user_type_changes(
        principal=alice, user_id=people["bob"]
    )

    assert (changed.user_type, changed.email, changed.first_name) == (
        UserType.AUTHOR,
        "bob@auth0.example.test",
        "Bob",
    )
    assert (change.changed_by_user_id, change.changed_by_email) == (
        people["alice"],
        "alice@auth0.example.test",
    )
    assert reader.profile_reads == [("google-oauth2|bob",), ("google-oauth2|alice",)]


def test_the_default_profile_source_needs_profile_settings_and_the_users_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from policyengine_api.fastapi_routes import dependencies
    from policyengine_api.libs import auth0_management

    for name in (
        "AUTH0_USER_PROFILES_DOMAIN",
        "AUTH0_USER_PROFILES_CLIENT_ID",
        "AUTH0_USER_PROFILES_CLIENT_SECRET",
        "AUTH0_USER_PROFILES_CLIENT_SECRET_RESOURCE",
        "PUBLIC_API_AUTH_REQUIRED",
        "PUBLIC_API_AUTH_ISSUER",
        "PUBLIC_API_AUTH_AUDIENCE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(auth0_management, "_shared_clients", {})

    assert dependencies._default_user_profile_source() is None
    monkeypatch.setenv("AUTH0_USER_PROFILES_DOMAIN", "policyengine.us.auth0.com")
    monkeypatch.setenv("AUTH0_USER_PROFILES_CLIENT_ID", "profile-reader")
    monkeypatch.setenv("AUTH0_USER_PROFILES_CLIENT_SECRET", "raw-profile-secret")
    # Without the users' issuer no identity can be matched to an Auth0 user.
    assert dependencies._default_user_profile_source() is None
    monkeypatch.setenv("PUBLIC_API_AUTH_ISSUER", "https://auth.example.test")
    monkeypatch.setenv("PUBLIC_API_AUTH_AUDIENCE", "https://api.policyengine.org/")

    source = dependencies._default_user_profile_source()

    assert source is not None
    assert source.issuer == "https://auth.example.test/"
    assert source.reader is auth0_management.build_auth0_user_profile_reader()
