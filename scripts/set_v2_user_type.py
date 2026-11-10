#!/usr/bin/env python3
"""Set the type of the one signed-in v2 user with an email address.

Usage::

    set_v2_user_type.py --email ada@example.org --user-type admin

The email is compared whole, ignoring case, with the user's own email and its
sign-in identities' emails; exactly one signed-in user must match. The change
is recorded in the user's type history with no admin named. Demoting the last
admin is refused, as it is through the admin routes.

It connects as the Public API's runtime role, configured as the deployed
Public API is: ``V2_RUNTIME_DATABASE_URL`` (or
``V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE``), ``V2_SUPABASE_PROJECT_REF`` and
``V2_SUPABASE_ENVIRONMENT``. A user exists only after that person's first
signed-in request to the detailed-save routes (``/v2/me`` and others).
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Protocol

from policyengine_api.data.v2.models import SIGNED_IN_USER_TYPES, UserType
from policyengine_api.services.v2.user_types.validators import (
    LastAdminDemotionError,
    UserEmailMatchError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from policyengine_api.services.v2.user_types.types import (
        ScriptedUserTypeChange,
    )


class UserTypeSetter(Protocol):
    """The user-type service operation this command calls."""

    def set_user_type_by_email(
        self, *, email: str, user_type: UserType
    ) -> ScriptedUserTypeChange:
        """Set the type of the one signed-in user with ``email``."""
        ...


def _runtime_user_type_service() -> UserTypeSetter:
    """Build the user-type service on the runtime role's database connection."""
    # These modules are imported only when the command runs, as they read the
    # database settings or need the connection.
    from policyengine_api.data.v2.database import (
        get_v2_session_factory,
    )
    from policyengine_api.services.v2.user_types.database_session import (
        UserTypeDatabaseSession,
    )
    from policyengine_api.services.v2.user_types.services import (
        V2UserTypeService,
    )

    return V2UserTypeService(UserTypeDatabaseSession(get_v2_session_factory()))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Set the type of the one signed-in v2 user with an email."
    )
    parser.add_argument("--email", required=True, help="The user's whole email")
    parser.add_argument(
        "--user-type",
        required=True,
        choices=[user_type.value for user_type in SIGNED_IN_USER_TYPES],
        help="The signed-in type to give the user",
    )
    return parser


def _describe(change: ScriptedUserTypeChange, email: str) -> str:
    user = change.user
    if change.previous_user_type is user.user_type:
        return (
            f"{email} (user {user.id}) is already {user.user_type.value}; "
            "nothing changed."
        )
    return (
        f"Changed {email} (user {user.id}) from "
        f"{change.previous_user_type.value} to {user.user_type.value}."
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    user_type_service_factory: Callable[[], UserTypeSetter] = (
        _runtime_user_type_service
    ),
) -> int:
    """Set one user's type; return 0 on success and 1 when it is refused.

    Any other failure, such as missing settings or an unreachable database,
    raises, so Python prints its traceback and also exits with 1.
    """
    arguments = _parser().parse_args(argv)
    try:
        change = user_type_service_factory().set_user_type_by_email(
            email=arguments.email, user_type=UserType(arguments.user_type)
        )
    except (UserEmailMatchError, LastAdminDemotionError) as error:
        print(error, file=sys.stderr)
        return 1
    print(_describe(change, arguments.email))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
