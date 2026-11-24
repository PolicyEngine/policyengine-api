"""Check the withheld area codes revision against disposable Postgres.

Revision 1e1e3f079f2c, on the SPM availability revision 0c136a278f29, adds
``withheld_area_codes`` and its ``v2_uk_area_type`` enum and changes no other
table. Each row names a UK area that disclosure control withheld from a
report run's local-area results. The downgrade drops the table, with its rows,
then the type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql.base import PGInspector
from sqlalchemy.exc import DataError, IntegrityError
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Report,
    ReportRun,
    Simulation,
    SimulationRun,
    WithheldAreaCode,
)
from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    add_row,
    insert_public_api_rows,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

SPM_AVAILABILITY_REVISION = "0c136a278f29"
WITHHELD_AREA_CODES_REVISION = "1e1e3f079f2c"


def _schema_shape(sessions: sessionmaker[Session]) -> dict[str, dict[str, Any]]:
    """Reflect every table's columns, keys, indexes and checks."""
    with sessions() as session:
        inspector = schema_inspector(session)
        return {
            table_name: {
                "columns": [
                    (
                        column["name"],
                        str(column["type"]),
                        column["nullable"],
                        column.get("default"),
                    )
                    for column in inspector.get_columns(table_name)
                ],
                "primary_key": inspector.get_pk_constraint(table_name),
                "foreign_keys": sorted(
                    (
                        key["name"],
                        key["constrained_columns"],
                        key["referred_table"],
                        key["options"].get("ondelete"),
                    )
                    for key in inspector.get_foreign_keys(table_name)
                ),
                "unique_constraints": sorted(
                    (unique["name"], unique["column_names"])
                    for unique in inspector.get_unique_constraints(table_name)
                ),
                "indexes": sorted(
                    (index["name"], index["column_names"])
                    for index in inspector.get_indexes(table_name)
                ),
                "checks": {
                    check["name"]: check["sqltext"]
                    for check in inspector.get_check_constraints(table_name)
                },
            }
            for table_name in inspector.get_table_names(schema="public")
            if table_name != "alembic_version"
        }


def _enum_labels(sessions: sessionmaker[Session]) -> dict[str, list[str]]:
    """Return each enum type in the public schema with its labels in order."""
    inspector = schema_inspector(sessions)
    assert isinstance(inspector, PGInspector)
    return {
        enum_type["name"]: enum_type["labels"]
        for enum_type in inspector.get_enums(schema="public")
    }


def _table_names(sessions: sessionmaker[Session]) -> list[str]:
    return schema_inspector(sessions).get_table_names()


@pytest.fixture
def sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    """Yield the disposable database owner's Session factories; leave it at head."""
    try:
        yield v2_owner_sessions
    finally:
        command.upgrade(alembic_v2_config(), "head")


def test_withheld_area_codes_revision_adds_only_the_table_and_its_type(
    sessions: sessionmaker[Session],
) -> None:
    """The revision adds one table and one enum type and changes nothing else."""
    config = alembic_v2_config()

    command.upgrade(config, "head")
    command.downgrade(config, SPM_AVAILABILITY_REVISION)
    parent_shape = _schema_shape(sessions)
    parent_enums = _enum_labels(sessions)
    command.upgrade(config, WITHHELD_AREA_CODES_REVISION)
    revision_shape = _schema_shape(sessions)
    revision_enums = _enum_labels(sessions)

    assert set(revision_shape) - set(parent_shape) == {"withheld_area_codes"}
    assert {
        table_name: shape
        for table_name, shape in revision_shape.items()
        if table_name != "withheld_area_codes"
    } == parent_shape
    assert revision_enums == {
        **parent_enums,
        "v2_uk_area_type": ["constituency", "local_authority"],
    }
    withheld = revision_shape["withheld_area_codes"]
    assert withheld["primary_key"]["constrained_columns"] == ["id"]
    assert withheld["unique_constraints"] == [
        (
            "uq_withheld_area_codes_run_type_code",
            ["report_run_id", "area_type", "code"],
        )
    ]
    assert sorted(
        (columns, referred_table, ondelete)
        for _name, columns, referred_table, ondelete in withheld["foreign_keys"]
    ) == [
        (["baseline_simulation_run_id"], "simulation_runs", "RESTRICT"),
        (["reform_simulation_run_id"], "simulation_runs", "RESTRICT"),
        (["report_run_id"], "report_runs", "CASCADE"),
    ]


def test_withheld_area_codes_downgrade_removes_the_table_and_its_type(
    sessions: sessionmaker[Session],
) -> None:
    """Downgrading drops the table and the type, so upgrading again works."""
    config = alembic_v2_config()

    command.upgrade(config, "head")
    command.downgrade(config, WITHHELD_AREA_CODES_REVISION)
    command.downgrade(config, SPM_AVAILABILITY_REVISION)

    assert "withheld_area_codes" not in _table_names(sessions)
    assert "v2_uk_area_type" not in _enum_labels(sessions)

    command.upgrade(config, WITHHELD_AREA_CODES_REVISION)

    assert "withheld_area_codes" in _table_names(sessions)
    assert _enum_labels(sessions)["v2_uk_area_type"] == [
        "constituency",
        "local_authority",
    ]


def _insert_report_run(session: Session) -> dict[str, UUID]:
    """Store a UK report run comparing two simulation runs, and a spare run."""
    public_api_rows = insert_public_api_rows(session)
    run_names = ("baseline_run", "reform_run", "unrelated_run")
    ids = {name: uuid4() for name in (*run_names, "report", "report_run")}
    # Each run is of a simulation of its own: a simulation has one unfailed
    # run per version set.
    for run_name in run_names:
        simulation_id = uuid4()
        add_row(
            session,
            Simulation,
            id=simulation_id,
            simulation_type="economy",
            dataset_id=public_api_rows.dataset_id,
            tax_benefit_model_version_id=public_api_rows.version_id,
            year=2026,
        )
        add_row(
            session,
            SimulationRun,
            id=ids[run_name],
            simulation_id=simulation_id,
            tax_benefit_model_version_id=public_api_rows.version_id,
            year=2026,
            status="pending",
            **RUN_VERSIONS,
        )
    add_row(
        session,
        Report,
        id=ids["report"],
        country="uk",
        tax_benefit_model_id=public_api_rows.model_id,
        year=2026,
        inputs={},
    )
    add_row(
        session,
        ReportRun,
        id=ids["report_run"],
        report_id=ids["report"],
        baseline_simulation_run_id=ids["baseline_run"],
        reform_simulation_run_id=ids["reform_run"],
        status="pending",
        **RUN_VERSIONS,
    )
    return ids


def _insert_withheld_code(
    session: Session,
    ids: dict[str, UUID],
    *,
    area_type: str,
    code: str,
    reform_run: str = "reform_run",
) -> None:
    add_row(
        session,
        WithheldAreaCode,
        id=uuid4(),
        report_run_id=ids["report_run"],
        baseline_simulation_run_id=ids["baseline_run"],
        reform_simulation_run_id=ids[reform_run],
        area_type=area_type,
        code=code,
    )


def _withheld_codes(session: Session, report_run_id: UUID) -> list[tuple[str, str]]:
    return list(
        session.execute(
            select(col(WithheldAreaCode.area_type), col(WithheldAreaCode.code))
            .where(col(WithheldAreaCode.report_run_id) == report_run_id)
            .order_by(col(WithheldAreaCode.area_type), col(WithheldAreaCode.code))
        ).tuples()
    )


def test_withheld_area_codes_hold_each_area_once_and_go_with_their_run(
    sessions: sessionmaker[Session],
) -> None:
    """Each run lists an area once, of a known type; deleting the run drops it."""
    command.upgrade(alembic_v2_config(), "head")

    with sessions() as session:
        try:
            ids = _insert_report_run(session)
            _insert_withheld_code(
                session, ids, area_type="constituency", code="E14001063"
            )
            # The same code under the other area type is a different area.
            _insert_withheld_code(
                session, ids, area_type="local_authority", code="E14001063"
            )
            _insert_withheld_code(
                session,
                ids,
                area_type="local_authority",
                code="E06000001",
                reform_run="unrelated_run",
            )

            with refused(session, IntegrityError, match="uq_withheld_area_codes"):
                _insert_withheld_code(
                    session, ids, area_type="constituency", code="E14001063"
                )
            with refused(session, DataError, match="v2_uk_area_type"):
                _insert_withheld_code(session, ids, area_type="ward", code="E05000001")
            # A simulation run that withheld codes name stays while they do.
            with refused(session, IntegrityError, match="withheld_area_codes"):
                session.execute(
                    delete(SimulationRun).where(
                        col(SimulationRun.id) == ids["unrelated_run"]
                    )
                )
            assert _withheld_codes(session, ids["report_run"]) == [
                ("constituency", "E14001063"),
                ("local_authority", "E06000001"),
                ("local_authority", "E14001063"),
            ]

            session.execute(
                delete(ReportRun).where(col(ReportRun.id) == ids["report_run"])
            )

            assert _withheld_codes(session, ids["report_run"]) == []
        finally:
            session.rollback()
