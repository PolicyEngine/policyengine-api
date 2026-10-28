"""Repointing a saved report or simulation against migrated Postgres.

The saved record's references are checked with the simulation service before
the update's transaction opens, so the update locks the saved row and refuses
it if another update changed the row meanwhile. The services run as the
Public API's runtime role.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from policyengine_api.constants import REPO
from policyengine_api.services.v2.associations.validators import (
    AssociationConflictError,
)
from policyengine_api.services.v2.simulation_refs.services import (
    SimulationReferenceService,
)
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
from tests.unit.v2.economy_report_support import (
    REPORT_ID,
    FakeEconomyReportSimulation,
    report_record,
    simulation_record,
)
from tests.unit.v2.user_service_support import ALICE, default_legacy_references

MIGRATED_SIMULATION_ID = UUID("00000000-0000-4000-8000-000000000194")
LOCK_WAIT_SECONDS = 10


@pytest.fixture
def engines(managed_v2_roles, v2_engine_as_role, disposable_v2_database_url):
    """Migrate, then yield the runtime role's sessions and an owner engine."""
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    owner_engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    runtime_engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    try:
        yield sessionmaker(runtime_engine, class_=Session), owner_engine
    finally:
        owner_engine.dispose()
        runtime_engine.dispose()


def _entrypoint() -> FakeEconomyReportSimulation:
    entrypoint = FakeEconomyReportSimulation(report_record(legacy_report_id=615))
    entrypoint.simulations[MIGRATED_SIMULATION_ID] = simulation_record(
        MIGRATED_SIMULATION_ID, legacy_simulation_id=613
    )
    return entrypoint


def _wait_for_a_blocked_update(owner_engine) -> None:
    """Wait until another session waits for a row lock."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        with owner_engine.connect() as connection:
            waiting = connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock'"
                )
            ).scalar_one()
        if waiting:
            return
        time.sleep(0.05)
    pytest.fail("the update never waited for the locked row")


@dataclass(frozen=True)
class RowChange:
    """Another update's change to one saved row: ``column`` set to ``value``."""

    table: str
    column: str
    value: int
    row_id: UUID


def _repoint_while_the_row_changes(owner_engine, change: RowChange, repoint) -> None:
    """Lock the row, start ``repoint``, change the row once it waits, then commit."""
    with owner_engine.connect() as owner, ThreadPoolExecutor(max_workers=1) as pool:
        owner.execute(
            text(f"SELECT id FROM {change.table} WHERE id = :row_id FOR UPDATE"),
            {"row_id": change.row_id},
        )
        repointed = pool.submit(repoint)
        _wait_for_a_blocked_update(owner_engine)
        owner.execute(
            text(
                f"UPDATE {change.table} SET {change.column} = :value WHERE id = :row_id"
            ),
            {"value": change.value, "row_id": change.row_id},
        )
        owner.commit()
        with pytest.raises(AssociationConflictError):
            repointed.result(timeout=LOCK_WAIT_SECONDS)


def test_postgres_saved_report_changed_during_its_check_is_not_repointed(
    engines,
) -> None:
    sessions, owner_engine = engines
    service = V2UserReportService(
        UserReportDatabaseSession(sessions),
        default_legacy_references(),
        SimulationReferenceService(_entrypoint()),
    )
    saved = service.create_user_report(
        principal=ALICE,
        association_input=UserReportCreateFields(country_id="us", legacy_report_id=615),
    )

    _repoint_while_the_row_changes(
        owner_engine,
        RowChange("user_report_associations", "legacy_report_id", 616, saved.id),
        lambda: service.patch_user_report(
            principal=ALICE,
            country_id="us",
            association_id=saved.id,
            association_input=UserReportUpdateInput(report_id=REPORT_ID),
        ),
    )

    with owner_engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT report_id, legacy_report_id FROM user_report_associations "
                "WHERE id = :row_id"
            ),
            {"row_id": saved.id},
        ).one()
    assert tuple(stored) == (None, 616)


def test_postgres_saved_simulation_changed_during_its_check_is_not_repointed(
    engines,
) -> None:
    sessions, owner_engine = engines
    service = V2UserSimulationService(
        UserSimulationDatabaseSession(sessions),
        default_legacy_references(),
        SimulationReferenceService(_entrypoint()),
    )
    saved = service.create_user_simulation(
        principal=ALICE,
        association_input=UserSimulationCreateFields(
            country_id="us", legacy_simulation_id=613
        ),
    )

    _repoint_while_the_row_changes(
        owner_engine,
        RowChange(
            "user_simulation_associations", "legacy_simulation_id", 614, saved.id
        ),
        lambda: service.patch_user_simulation(
            principal=ALICE,
            country_id="us",
            association_id=saved.id,
            association_input=UserSimulationUpdateInput(
                simulation_id=MIGRATED_SIMULATION_ID
            ),
        ),
    )

    with owner_engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT simulation_id, legacy_simulation_id "
                "FROM user_simulation_associations WHERE id = :row_id"
            ),
            {"row_id": saved.id},
        ).one()
    assert tuple(stored) == (None, 614)
