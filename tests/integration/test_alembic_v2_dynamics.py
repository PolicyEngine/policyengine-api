"""Check the revision that stores dynamics like policies against disposable Postgres.

The revision gives ``dynamics`` policies' columns and drops ``name`` and
``description``, adds a partial unique index on a dynamic's values, and adds
``legacy_policy_mappings.dynamic_id``, a key to a dynamic of the mapping's
country. Nothing else changes. Its new required columns have no default, so
the upgrade fails while ``dynamics`` has a row, and the downgrade, which adds
``name`` back as required, fails the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import String, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, registry
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Dynamic,
    LegacyPolicyMapping,
    Policy,
)
from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config, table_columns
from tests.integration.alembic_version_rows import current_revision
from tests.integration.simulation_rows import (
    PublicApiRows,
    add_row,
    delete_public_api_rows,
    insert_public_api_rows,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

PREVIOUS_REVISION = "f519a77ba122"
DYNAMICS_REVISION = "9d1d12a7ac58"
CHANGED_TABLES = frozenset({"dynamics", "legacy_policy_mappings", "parameter_values"})

previous_revision_tables = registry()


@previous_revision_tables.mapped
class DynamicAtF519a77ba122:
    """The ``dynamics`` table at revision f519a77ba122, before this revision.

    A dynamic then had a required name and a description. ``created_at`` and
    ``updated_at``, which the database fills in, aren't mapped.
    """

    __tablename__ = "dynamics"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None]


@pytest.fixture
def sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    """Yield the owner's Session factories on a database at head; leave it at head.

    ``v2_owner_sessions`` checks that the target is the disposable database
    before this migrates it.
    """
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


def _schema(sessions: sessionmaker[Session]) -> dict[str, dict[str, Any]]:
    """Return each table's columns, keys, checks and indexes, comparably."""
    with sessions() as session:
        inspector = schema_inspector(session)
        return {
            table_name: {
                "columns": sorted(
                    (column["name"], str(column["type"]), column["nullable"])
                    for column in inspector.get_columns(table_name)
                ),
                "foreign_keys": sorted(
                    (
                        str(key["name"]),
                        tuple(key["constrained_columns"]),
                        key["referred_table"],
                        tuple(key["referred_columns"]),
                        key["options"].get("ondelete"),
                    )
                    for key in inspector.get_foreign_keys(table_name)
                ),
                "unique": sorted(
                    (str(constraint["name"]), tuple(constraint["column_names"]))
                    for constraint in inspector.get_unique_constraints(table_name)
                ),
                "checks": sorted(
                    (str(check["name"]), check["sqltext"])
                    for check in inspector.get_check_constraints(table_name)
                ),
                "indexes": sorted(
                    (
                        str(index["name"]),
                        tuple(str(column) for column in index["column_names"]),
                        bool(index["unique"]),
                        str(index.get("dialect_options", {}).get("postgresql_where")),
                    )
                    for index in inspector.get_indexes(table_name)
                ),
            }
            for table_name in inspector.get_table_names()
        }


def _insert_dynamic(
    session: Session,
    rows: PublicApiRows,
    *,
    content_hash: str = "d" * 64,
    country_id: str = "us",
) -> UUID:
    dynamic_id = uuid4()
    add_row(
        session,
        Dynamic,
        id=dynamic_id,
        country_id=country_id,
        tax_benefit_model_id=rows.model_id,
        tax_benefit_model_version_id=rows.version_id,
        canonicalization_version=1,
        content_hash=content_hash,
    )
    return dynamic_id


def _insert_policy(session: Session, rows: PublicApiRows, *, country_id: str) -> UUID:
    policy_id = uuid4()
    add_row(
        session,
        Policy,
        id=policy_id,
        country_id=country_id,
        tax_benefit_model_id=rows.model_id,
        tax_benefit_model_version_id=rows.version_id,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    return policy_id


def _delete_dynamic(session: Session, dynamic_id: UUID) -> None:
    session.execute(delete(Dynamic).where(col(Dynamic.id) == dynamic_id))


def test_the_revision_changes_only_dynamics_their_values_and_mappings(
    sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()
    command.downgrade(config, PREVIOUS_REVISION)
    before = _schema(sessions)
    command.upgrade(config, DYNAMICS_REVISION)
    after = _schema(sessions)

    assert {name: before[name] for name in before if name not in CHANGED_TABLES} == {
        name: after[name] for name in after if name not in CHANGED_TABLES
    }
    assert {column[0] for column in after["dynamics"]["columns"]} == {
        column[0] for column in after["policies"]["columns"]
    }
    assert {column[0] for column in before["dynamics"]["columns"]} == {
        "id",
        "created_at",
        "updated_at",
        "name",
        "description",
    }
    assert set(after["legacy_policy_mappings"]["columns"]) - set(
        before["legacy_policy_mappings"]["columns"]
    ) == {("dynamic_id", "UUID", True)}
    assert set(after["legacy_policy_mappings"]["foreign_keys"]) - set(
        before["legacy_policy_mappings"]["foreign_keys"]
    ) == {
        (
            "fk_legacy_policy_mappings_dynamic_country",
            ("dynamic_id", "country_id"),
            "dynamics",
            ("id", "country_id"),
            "RESTRICT",
        )
    }
    assert set(after["parameter_values"]["indexes"]) - set(
        before["parameter_values"]["indexes"]
    ) == {
        (
            "uq_parameter_values_dynamic_parameter_start_date",
            ("dynamic_id", "parameter_id", "start_date"),
            True,
            "(dynamic_id IS NOT NULL)",
        )
    }
    assert {
        key: value
        for key, value in after["parameter_values"].items()
        if key != "indexes"
    } == {
        key: value
        for key, value in before["parameter_values"].items()
        if key != "indexes"
    }

    command.downgrade(config, PREVIOUS_REVISION)
    assert _schema(sessions) == before
    command.upgrade(config, "head")
    command.check(config)


def test_a_dynamic_is_stored_once(session: Session) -> None:
    """A dynamic is unique by its content hash, which has 64 characters.

    The revision's partial unique index on a dynamic's ``parameter_values`` is
    gone at the head: revision 7f7335f0eb31 moved dynamics' values to
    ``dynamic_parameter_values``, which keeps that rule, and revision
    1c651058fac5 dropped ``parameter_values.dynamic_id`` with the index.
    """
    rows = insert_public_api_rows(session)
    _insert_dynamic(session, rows)

    with refused(session, match="uq_dynamics_canonicalization_content_hash"):
        _insert_dynamic(session, rows)
    with refused(session, match="ck_dynamics_content_hash_length"):
        _insert_dynamic(session, rows, content_hash="short")


def test_a_mapping_names_a_dynamic_of_its_country_which_stays_while_named(
    session: Session,
) -> None:
    rows = insert_public_api_rows(session)
    us_dynamic_id = _insert_dynamic(session, rows)
    us_policy_id = _insert_policy(session, rows, country_id="us")
    uk_policy_id = _insert_policy(session, rows, country_id="uk")

    with refused(session, match="fk_legacy_policy_mappings_dynamic_country"):
        add_row(
            session,
            LegacyPolicyMapping,
            id=uuid4(),
            country_id="uk",
            legacy_policy_id=1,
            policy_id=uk_policy_id,
            dynamic_id=us_dynamic_id,
            source_policy_hash="v1-hash",
        )
    add_row(
        session,
        LegacyPolicyMapping,
        id=uuid4(),
        country_id="us",
        legacy_policy_id=1,
        policy_id=us_policy_id,
        dynamic_id=us_dynamic_id,
        source_policy_hash="v1-hash",
    )
    # A mapping without a dynamic is unaffected.
    add_row(
        session,
        LegacyPolicyMapping,
        id=uuid4(),
        country_id="us",
        legacy_policy_id=2,
        policy_id=us_policy_id,
        source_policy_hash="v1-hash-2",
    )
    with refused(session, match="fk_legacy_policy_mappings_dynamic_country"):
        _delete_dynamic(session, us_dynamic_id)


def test_the_upgrade_fails_changing_nothing_while_a_dynamic_is_stored(
    sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()
    command.downgrade(config, PREVIOUS_REVISION)
    dynamic_id = uuid4()
    with sessions.begin() as session:
        add_row(session, DynamicAtF519a77ba122, id=dynamic_id, name="stored before")
    try:
        with pytest.raises(IntegrityError, match="country_id"):
            command.upgrade(config, DYNAMICS_REVISION)
        assert current_revision(sessions) == PREVIOUS_REVISION
        assert "name" in table_columns(sessions, "dynamics")
    finally:
        with sessions.begin() as session:
            session.execute(
                delete(DynamicAtF519a77ba122).where(
                    DynamicAtF519a77ba122.id == dynamic_id
                )
            )


def test_the_downgrade_fails_changing_nothing_while_a_dynamic_is_stored(
    sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()
    # The fixture upgrades to the head before the test, and the head can be
    # later than the dynamics revision, so a downgrade reaches it; an upgrade
    # to an older revision does nothing.
    command.downgrade(config, DYNAMICS_REVISION)
    with sessions.begin() as session:
        rows = insert_public_api_rows(session)
        dynamic_id = _insert_dynamic(session, rows)
    try:
        with pytest.raises(IntegrityError, match="name"):
            command.downgrade(config, PREVIOUS_REVISION)
        assert current_revision(sessions) == DYNAMICS_REVISION
        assert "dynamic_id" in table_columns(sessions, "legacy_policy_mappings")
    finally:
        with sessions.begin() as session:
            _delete_dynamic(session, dynamic_id)
            delete_public_api_rows(session, rows)
