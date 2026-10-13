"""Batched, read-only v1 existence checks through the v1 mapped models."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.data.v1_models import (
    Household,
    Policy,
    ReportOutput,
    Simulation,
)
from policyengine_api.services.v2.legacy_refs.database_connectors import reads
from policyengine_api.services.v2.legacy_refs.database_session import (
    LegacyReferenceDatabaseSession,
)
from policyengine_api.services.v2.legacy_refs.services import (
    V1LegacyReferenceService,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)


@pytest.fixture
def v1_sessions():
    engine = sa.create_engine("sqlite://")
    # SQLite cannot autoincrement inside v1's composite policy key, so the
    # physical test tables come from detached copies without that option.
    sqlite_metadata = sa.MetaData()
    for model in (Policy, Household, Simulation, ReportOutput):
        copy = model.__table__.to_metadata(sqlite_metadata)
        copy.c.id.autoincrement = False
    sqlite_metadata.create_all(engine)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    with sessions.begin() as session:
        session.add_all(
            [
                Policy(
                    id=1,
                    country_id="us",
                    api_version="1",
                    policy_json={},
                    policy_hash="a",
                ),
                Policy(
                    id=2,
                    country_id="uk",
                    api_version="1",
                    policy_json={},
                    policy_hash="b",
                ),
                Household(
                    id=10,
                    country_id="us",
                    api_version="1",
                    household_json={},
                    household_hash="h",
                ),
                Simulation(
                    id=613,
                    country_id="us",
                    api_version="1",
                    population_id="us",
                    population_type="geography",
                    policy_id=1,
                ),
                ReportOutput(
                    id=615,
                    country_id="us",
                    simulation_1_id=613,
                    api_version="1",
                ),
            ]
        )
    yield sessions
    engine.dispose()


def test_existing_ids_are_country_scoped_and_batched(v1_sessions, monkeypatch) -> None:
    monkeypatch.setattr(reads, "READ_BATCH_SIZE", 1)
    statements: list[str] = []
    engine = v1_sessions.kw["bind"]

    def record(_conn, _cursor, statement, _parameters, _context, _many) -> None:
        statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", record)
    service = V1LegacyReferenceService(LegacyReferenceDatabaseSession(v1_sessions))

    existing = service.existing_ids(
        country_id="us",
        requested={
            LegacyRecordKind.POLICY: [1, 2, 3],
            LegacyRecordKind.HOUSEHOLD: [10],
            LegacyRecordKind.SIMULATION: [613, 613],
            LegacyRecordKind.REPORT: [],
        },
    )

    assert existing == {
        LegacyRecordKind.POLICY: frozenset({1}),
        LegacyRecordKind.HOUSEHOLD: frozenset({10}),
        LegacyRecordKind.SIMULATION: frozenset({613}),
        LegacyRecordKind.REPORT: frozenset(),
    }
    selects = [statement for statement in statements if "SELECT" in statement]
    assert len(selects) == 5
    assert all("country_id" in statement for statement in selects)
    assert not any(
        keyword in statement
        for statement in statements
        for keyword in ("INSERT", "UPDATE", "DELETE")
    )


def test_missing_references_raise_the_422_error(v1_sessions) -> None:
    service = V1LegacyReferenceService(LegacyReferenceDatabaseSession(v1_sessions))

    service.require_existing(
        country_id="us", requested={LegacyRecordKind.REPORT: [615]}
    )
    with pytest.raises(LegacyReferenceNotFoundError, match="v1 report 616"):
        service.require_existing(
            country_id="us", requested={LegacyRecordKind.REPORT: [615, 616]}
        )
    with pytest.raises(LegacyReferenceNotFoundError, match="country uk"):
        service.require_existing(
            country_id="uk", requested={LegacyRecordKind.POLICY: [1]}
        )


def test_empty_requests_open_no_v1_session() -> None:
    def reject_session():
        raise AssertionError("no v1 session should be opened")

    service = V1LegacyReferenceService(
        LegacyReferenceDatabaseSession(reject_session)  # type: ignore[arg-type]
    )

    assert service.existing_ids(
        country_id="us", requested={LegacyRecordKind.POLICY: []}
    ) == {LegacyRecordKind.POLICY: frozenset()}


def test_deferred_service_builds_the_v1_service_once_on_first_check() -> None:
    from policyengine_api.services.v2.legacy_refs.services import (
        DeferredLegacyReferenceService,
    )

    builds: list[int] = []

    class Built:
        def existing_ids(self, *, country_id, requested):
            return {kind: frozenset(ids) for kind, ids in requested.items()}

        def require_existing(self, *, country_id, requested):
            return None

    def build():
        builds.append(1)
        return Built()

    deferred = DeferredLegacyReferenceService(build)
    assert builds == []

    deferred.require_existing(
        country_id="us", requested={LegacyRecordKind.POLICY: (1,)}
    )
    assert deferred.existing_ids(
        country_id="us", requested={LegacyRecordKind.POLICY: (2,)}
    ) == {LegacyRecordKind.POLICY: frozenset({2})}
    assert builds == [1]


def test_default_reference_checker_does_not_touch_the_v1_database(
    monkeypatch,
) -> None:
    from policyengine_api.data import orm
    from policyengine_api.fastapi_routes import dependencies

    def unavailable():
        raise RuntimeError("v1 database is not configured")

    monkeypatch.setattr(orm, "get_v1_session_factory", unavailable)

    checker = dependencies._default_legacy_reference_checker()

    with pytest.raises(RuntimeError, match="not configured"):
        checker.require_existing(
            country_id="us", requested={LegacyRecordKind.POLICY: (1,)}
        )
