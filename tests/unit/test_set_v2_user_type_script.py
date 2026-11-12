"""Tests for the command that sets a signed-in user's type by email."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import UserType
from policyengine_api.services.v2.user_types.types import (
    AdminUserRead,
    ScriptedUserTypeChange,
)
from policyengine_api.services.v2.user_types.validators import (
    LastAdminDemotionError,
    UserEmailMatchError,
)
from scripts import set_v2_user_type

USER_ID = UUID("00000000-0000-0000-0000-000000000091")


class FakeUserTypes:
    """Record each call and return ``previous_user_type`` or raise ``error``."""

    def __init__(
        self,
        previous_user_type: UserType = UserType.STANDARD,
        error: Exception | None = None,
    ) -> None:
        self.previous_user_type = previous_user_type
        self.error = error
        self.calls: list[dict] = []

    def set_user_type_by_email(
        self, *, email: str, user_type: UserType
    ) -> ScriptedUserTypeChange:
        self.calls.append({"email": email, "user_type": user_type})
        if self.error is not None:
            raise self.error
        return ScriptedUserTypeChange(
            user=AdminUserRead(
                id=USER_ID,
                user_type=user_type,
                email=email,
                first_name=None,
                last_name=None,
                primary_country="us",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                last_seen_at=None,
            ),
            previous_user_type=self.previous_user_type,
        )


def test_the_command_sets_a_type_and_says_what_changed(capsys) -> None:
    user_types = FakeUserTypes()

    status = set_v2_user_type.main(
        ["--email", "ada@example.test", "--user-type", "admin"],
        user_type_service_factory=lambda: user_types,
    )

    assert status == 0
    assert user_types.calls == [
        {"email": "ada@example.test", "user_type": UserType.ADMIN}
    ]
    assert capsys.readouterr().out == (
        f"Changed ada@example.test (user {USER_ID}) from standard to admin.\n"
    )


def test_the_command_says_when_nothing_changed(capsys) -> None:
    user_types = FakeUserTypes(previous_user_type=UserType.AUTHOR)

    status = set_v2_user_type.main(
        ["--email", "ada@example.test", "--user-type", "author"],
        user_type_service_factory=lambda: user_types,
    )

    assert status == 0
    assert capsys.readouterr().out == (
        f"ada@example.test (user {USER_ID}) is already author; nothing changed.\n"
    )


@pytest.mark.parametrize(
    "error",
    [
        UserEmailMatchError("no signed-in user has the email ada@example.test"),
        LastAdminDemotionError("The last admin can't be demoted"),
    ],
)
def test_the_command_reports_a_refusal_and_fails(capsys, error: Exception) -> None:
    status = set_v2_user_type.main(
        ["--email", "ada@example.test", "--user-type", "standard"],
        user_type_service_factory=lambda: FakeUserTypes(error=error),
    )

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert captured.err == f"{error}\n"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--email", "ada@example.test"],
        ["--user-type", "admin"],
        ["--email", "ada@example.test", "--user-type", "unauthenticated"],
        ["--email", "ada@example.test", "--user-type", "editor"],
    ],
)
def test_the_command_refuses_missing_or_unknown_arguments(arguments) -> None:
    user_types = FakeUserTypes()

    with pytest.raises(SystemExit) as exit_info:
        set_v2_user_type.main(arguments, user_type_service_factory=lambda: user_types)

    assert exit_info.value.code == 2
    assert user_types.calls == []


def test_the_command_emails_the_user_whose_type_it_changed(monkeypatch) -> None:
    """The command's own service emails the user, as the admin routes do."""
    from policyengine_api.data.v2 import database
    from policyengine_api.fastapi_routes import dependencies
    from policyengine_api.services.v2.identity.types import UserPrincipal
    from policyengine_api.services.v2.user_accounts.database_session import (
        AccountDatabaseSession,
    )
    from policyengine_api.services.v2.user_accounts.services import V2AccountService
    from tests.unit.v2.user_email_support import (
        RecordingEmailSender,
        StandInProfileReader,
        auth0_profile,
        profile_source,
    )
    from tests.unit.v2.user_service_support import ISSUER, v2_store

    ada = UserPrincipal(
        issuer=ISSUER, subject="google-oauth2|ada", email="ada@example.org"
    )
    sender = RecordingEmailSender()
    reader = StandInProfileReader([auth0_profile(ada.subject, "ada@auth0.test")])
    with v2_store() as store:
        V2AccountService(AccountDatabaseSession(store.sessions)).get_account(
            principal=ada, country_id="us"
        )
        monkeypatch.setattr(database, "get_v2_session_factory", lambda: store.sessions)
        monkeypatch.setattr(
            "policyengine_api.libs.postmark_email.build_postmark_email_sender",
            lambda: sender,
        )
        monkeypatch.setattr(
            dependencies,
            "_default_user_profile_source",
            lambda: profile_source(ISSUER, reader),
        )

        exit_code = set_v2_user_type.main(
            ["--email", "ada@example.org", "--user-type", "author"]
        )

    assert exit_code == 0
    assert [(email["to"], email["template_alias"]) for email in sender.sent] == [
        ("ada@auth0.test", "user-type-changed")
    ]
