"""A sign-in merge moves report-run records in any database the unit tests use.

PostgreSQL tests (``tests/integration/test_v2_user_report_runs.py``) check
which records move; these check that the merge's statements run in SQLite
too, where the user service tests merge accounts.
"""

from __future__ import annotations

from uuid import uuid4

from sqlmodel import select

from policyengine_api.data.v2.models import User
from policyengine_api.services.v2.identity.services import (
    convert_unauthenticated_user_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import (
    AccountConversionOutcome,
    UnauthenticatedPrincipal,
    UserPrincipal,
)
from tests.unit.v2.user_service_support import v2_store

ACCOUNT = UserPrincipal(issuer="https://users.example.test/", subject="auth0|merge")


def test_a_browser_without_run_records_merges_into_an_account() -> None:
    browser = UnauthenticatedPrincipal(user_id=uuid4())
    with v2_store() as store:
        with store.sessions.begin() as session:
            account_id = resolve_principal_user_in_session(
                session, ACCOUNT, country_id="us"
            ).user_id
            resolve_principal_user_in_session(session, browser, country_id="us")

        with store.sessions.begin() as session:
            conversion = convert_unauthenticated_user_in_session(
                session,
                unauthenticated_user_id=browser.user_id,
                principal=ACCOUNT,
                country_id="us",
            )

        with store.sessions() as session:
            user_ids = set(session.exec(select(User.id)).all())

    assert conversion.outcome is AccountConversionOutcome.MERGED
    assert user_ids == {account_id}
