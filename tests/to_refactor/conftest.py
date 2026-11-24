"""Explicit test-only persistence for the legacy route suite."""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data import orm
from policyengine_api.data.v1_models import Policy
from policyengine_api.utils import hash_object
from tests.fixtures.database_sessions import serve_v1_sessions, sqlite_v1_sessions


def _seed_current_law_policies(sessions: sessionmaker[Session]) -> None:
    policies = [
        Policy(
            id=policy_id,
            country_id=country_id,
            label="Current law",
            api_version=COUNTRY_PACKAGE_VERSIONS[country_id],
            policy_json={},
            policy_hash=hash_object({}),
        )
        for policy_id, country_id in enumerate(COUNTRY_PACKAGE_VERSIONS, start=1)
    ]
    with sessions.begin() as session:
        session.add_all(policies)


@pytest.fixture(scope="session", autouse=True)
def isolated_legacy_v1_database() -> Iterator[None]:
    """Bind legacy tests to explicit in-memory persistence, never Cloud SQL."""
    patcher = pytest.MonkeyPatch()
    with sqlite_v1_sessions() as sessions:
        _seed_current_law_policies(sessions)
        serve_v1_sessions(patcher, sessions)
        try:
            yield
        finally:
            orm.clear_v1_session_factories()
            patcher.undo()
