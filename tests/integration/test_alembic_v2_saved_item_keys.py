"""Check the saved-item keys revision against disposable Postgres.

The revision makes ``user_report_associations.report_id`` and
``user_simulation_associations.simulation_id`` foreign keys to ``reports`` and
``simulations``, both ``RESTRICT``: a saved report or simulation can't name a
row that doesn't exist, and a report or simulation a saved item names can't be
deleted. A saved item that names only its v1 report or simulation is
unaffected. The downgrade drops both keys and nothing else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Report,
    Simulation,
    User,
    UserReportAssociation,
    UserSimulationAssociation,
)
from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config
from tests.integration.alembic_version_rows import current_revision
from tests.integration.simulation_rows import (
    PublicApiRows,
    add_row,
    insert_public_api_rows,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

SAVED_ITEM_KEYS_PREVIOUS_REVISION = "1356f658347d"
SAVED_ITEM_KEYS_REVISION = "81b728a088e7"
SAVED_ITEM_KEYS = {
    "user_report_associations": (
        "fk_user_report_associations_report_id_reports",
        "report_id",
        "reports",
    ),
    "user_simulation_associations": (
        "fk_user_simulation_associations_simulation_id_simulations",
        "simulation_id",
        "simulations",
    ),
}
# Each association table's mapped class. Neither table's columns change between
# the previous revision and the head.
SAVED_ITEM_MODELS: dict[str, type[Any]] = {
    "user_report_associations": UserReportAssociation,
    "user_simulation_associations": UserSimulationAssociation,
}


@pytest.fixture
def sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    """Yield the owner's Session factories on a database at head; leave it at head."""
    command.upgrade(alembic_v2_config(), "head")
    try:
        yield v2_owner_sessions
    finally:
        command.upgrade(alembic_v2_config(), "head")


@pytest.fixture
def session(sessions: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a Session at head whose writes are rolled back after the test."""
    with sessions() as database_session:
        try:
            yield database_session
        finally:
            database_session.rollback()


def _saved_item_keys(
    sessions: sessionmaker[Session],
) -> dict[str, tuple[str | None, list[str], str, str | None]]:
    """Return each association table's keys to ``reports`` or ``simulations``."""
    inspector = schema_inspector(sessions)
    return {
        table_name: (
            key["name"],
            key["constrained_columns"],
            key["referred_table"],
            key["options"].get("ondelete"),
        )
        for table_name in SAVED_ITEM_KEYS
        for key in inspector.get_foreign_keys(table_name)
        if key["referred_table"] in {"reports", "simulations"}
    }


def _insert_user(session: Session) -> UUID:
    """Store a standard user, which needs a primary country."""
    user_id = uuid4()
    add_row(session, User, id=user_id, primary_country="us")
    return user_id


def _insert_simulation(session: Session, rows: PublicApiRows) -> UUID:
    simulation_id = uuid4()
    add_row(
        session,
        Simulation,
        id=simulation_id,
        simulation_type="economy",
        dataset_id=rows.dataset_id,
        tax_benefit_model_version_id=rows.version_id,
        year=2026,
    )
    return simulation_id


def _insert_report(session: Session, rows: PublicApiRows) -> UUID:
    report_id = uuid4()
    add_row(
        session,
        Report,
        id=report_id,
        country="us",
        tax_benefit_model_id=rows.model_id,
        inputs={},
    )
    return report_id


def _save(
    session: Session, model: type[Any], user_id: UUID, **reference: object
) -> UUID:
    saved_item_id = uuid4()
    add_row(
        session,
        model,
        id=saved_item_id,
        user_id=user_id,
        country_id="us",
        **reference,
    )
    return saved_item_id


def test_a_saved_item_must_name_a_stored_report_or_simulation(
    session: Session,
) -> None:
    rows = insert_public_api_rows(session)
    user_id = _insert_user(session)
    report_id = _insert_report(session, rows)
    simulation_id = _insert_simulation(session, rows)

    with refused(session, IntegrityError, match="fk_user_report_associations"):
        _save(session, UserReportAssociation, user_id, report_id=uuid4())
    with refused(session, IntegrityError, match="fk_user_simulation_associations"):
        _save(session, UserSimulationAssociation, user_id, simulation_id=uuid4())

    _save(session, UserReportAssociation, user_id, report_id=report_id)
    _save(session, UserSimulationAssociation, user_id, simulation_id=simulation_id)
    # A saved item that names only its v1 report or simulation is unaffected.
    _save(session, UserReportAssociation, user_id, legacy_report_id=42)
    _save(session, UserSimulationAssociation, user_id, legacy_simulation_id=42)


def test_a_report_or_simulation_a_saved_item_names_cannot_be_deleted(
    session: Session,
) -> None:
    rows = insert_public_api_rows(session)
    user_id = _insert_user(session)
    report_id = _insert_report(session, rows)
    simulation_id = _insert_simulation(session, rows)
    _save(session, UserReportAssociation, user_id, report_id=report_id)
    _save(session, UserSimulationAssociation, user_id, simulation_id=simulation_id)

    with refused(session, IntegrityError, match="fk_user_report_associations"):
        session.execute(delete(Report).where(col(Report.id) == report_id))
    with refused(session, IntegrityError, match="fk_user_simulation_associations"):
        session.execute(delete(Simulation).where(col(Simulation.id) == simulation_id))


def test_the_revision_adds_the_keys_and_drops_them_on_downgrade(
    sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()
    command.downgrade(config, SAVED_ITEM_KEYS_PREVIOUS_REVISION)
    command.upgrade(config, SAVED_ITEM_KEYS_REVISION)
    assert _saved_item_keys(sessions) == {
        table_name: (key_name, [column_name], referred_table, "RESTRICT")
        for table_name, (
            key_name,
            column_name,
            referred_table,
        ) in SAVED_ITEM_KEYS.items()
    }

    command.downgrade(config, SAVED_ITEM_KEYS_PREVIOUS_REVISION)
    assert _saved_item_keys(sessions) == {}

    command.upgrade(config, SAVED_ITEM_KEYS_REVISION)
    assert set(_saved_item_keys(sessions)) == set(SAVED_ITEM_KEYS)
    command.upgrade(config, "head")
    command.check(config)


@pytest.mark.parametrize(
    ("table_name", "reference"),
    [
        ("user_report_associations", {"report_id": uuid4()}),
        ("user_simulation_associations", {"simulation_id": uuid4()}),
    ],
)
def test_the_upgrade_fails_changing_nothing_while_a_saved_item_names_a_missing_row(
    sessions: sessionmaker[Session], table_name: str, reference: dict[str, object]
) -> None:
    """Adding a key checks every existing row, so the upgrade fails and stays put.

    Before the revision a saved item could name a report or simulation that
    doesn't exist; while one does, the upgrade fails inside its transaction,
    leaving the database at the parent revision with no new key.
    """
    config = alembic_v2_config()
    model = SAVED_ITEM_MODELS[table_name]
    command.downgrade(config, SAVED_ITEM_KEYS_PREVIOUS_REVISION)
    with sessions.begin() as session:
        user_id = _insert_user(session)
        saved_item_id = _save(session, model, user_id, **reference)
    try:
        with pytest.raises(IntegrityError, match=SAVED_ITEM_KEYS[table_name][0]):
            command.upgrade(config, SAVED_ITEM_KEYS_REVISION)
        assert current_revision(sessions) == SAVED_ITEM_KEYS_PREVIOUS_REVISION
        assert _saved_item_keys(sessions) == {}
    finally:
        with sessions.begin() as session:
            session.execute(delete(model).where(col(model.id) == saved_item_id))
            session.execute(delete(User).where(col(User.id) == user_id))
