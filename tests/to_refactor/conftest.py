"""Explicit test-only persistence for the legacy route suite."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS
from policyengine_api.data import orm
from policyengine_api.data.v1_models import Policy
from policyengine_api.utils import hash_object
from tests.fixtures.local_v1_database import create_test_v1_schema


def _seed_current_law_policies(engine: Engine) -> None:
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
    with orm.build_session_factory(engine).begin() as session:
        session.add_all(policies)


@pytest.fixture(scope="session", autouse=True)
def isolated_legacy_v1_database() -> Iterator[None]:
    """Bind legacy tests to explicit in-memory persistence, never Cloud SQL."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_test_v1_schema(engine)
    _seed_current_law_policies(engine)

    patcher = pytest.MonkeyPatch()
    patcher.setattr(orm, "get_v1_engine", lambda: engine)
    orm.clear_v1_session_factories()
    try:
        yield
    finally:
        orm.clear_v1_session_factories()
        patcher.undo()
        engine.dispose()
