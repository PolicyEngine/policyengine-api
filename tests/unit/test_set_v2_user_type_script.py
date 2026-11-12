"""Tests for the command that sets a signed-in user's type by email."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from uuid import UUID

import pytest

from policyengine_api.constants import REPO
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


def test_loading_the_command_leaves_the_observability_runtime_unbuilt() -> None:
    """The command and what its service factory loads mustn't build the runtime.

    Importing ``policyengine_api.observability`` builds the process-wide
    runtime, which adds a root log handler and, with no OTLP endpoint, writes
    an ERROR record to the command's output.
    """
    import_check = (
        "import sys\n"
        "import scripts.set_v2_user_type\n"
        "import policyengine_api.data.v2.database\n"
        "import policyengine_api.services.v2.user_types.database_session\n"
        "import policyengine_api.services.v2.user_types.services\n"
        "loaded = 'policyengine_api.observability' in sys.modules\n"
        "assert not loaded, 'the observability runtime was imported'\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", import_check],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
