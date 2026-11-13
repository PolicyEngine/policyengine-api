"""Identical requests share simulations, reports and runs (C1 · 24's design).

The simulation service finds each simulation and report by a key it computes,
and joins an existing run on the current versions instead of creating one.
The database enforces both: one row per key, and at most one unfailed,
unforced run per definition and version set. Each user's request is recorded
in ``user_report_run_associations``.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from policyengine_api.data.v2.models import (
    V2_METADATA,
    ReportRun,
    Simulation,
    SimulationRun,
    SimulationStatus,
)

UNFAILED_UNFORCED = "status <> 'failed' AND NOT forced"


def _checks(table_name: str) -> dict[str, str]:
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in V2_METADATA.tables[table_name].constraints
        if isinstance(constraint, sa.CheckConstraint)
    }


def _unique_constraints(table_name: str) -> dict[str, tuple[str, ...]]:
    return {
        str(constraint.name): tuple(column.name for column in constraint.columns)
        for constraint in V2_METADATA.tables[table_name].constraints
        if isinstance(constraint, sa.UniqueConstraint)
    }


def _index(table_name: str, index_name: str) -> sa.Index:
    return next(
        index
        for index in V2_METADATA.tables[table_name].indexes
        if index.name == index_name
    )


@pytest.mark.parametrize("table_name", ["simulations", "reports"])
def test_simulations_and_reports_are_found_by_an_optional_unique_key(
    table_name: str,
) -> None:
    """Existing rows stay unkeyed; a keyed row is unique on its key and version."""
    table = V2_METADATA.tables[table_name]

    assert table.c.key_version.nullable
    assert isinstance(table.c.key_version.type, sa.Integer)
    assert table.c.definition_key.nullable
    assert table.c.definition_key.type.length == 64
    assert _unique_constraints(table_name)[
        f"uq_{table_name}_key_version_definition_key"
    ] == ("key_version", "definition_key")
    checks = _checks(table_name)
    assert checks[f"ck_{table_name}_key_version"] == "key_version > 0"
    assert checks[f"ck_{table_name}_definition_key"] == (
        "length(definition_key) = 64 AND ltrim(definition_key, '0123456789abcdef') = ''"
    )


def test_a_keyed_simulation_names_its_key_version() -> None:
    assert _checks("simulations")["ck_simulations_keys_complete"] == (
        "(key_version IS NULL) = (definition_key IS NULL)"
    )


def test_a_keyed_report_also_has_the_key_shared_across_datasets() -> None:
    """A national report and its local-area report share dataset_independent_key."""
    reports = V2_METADATA.tables["reports"]
    checks = _checks("reports")

    assert reports.c.dataset_independent_key.nullable
    assert reports.c.dataset_independent_key.type.length == 64
    assert checks["ck_reports_dataset_independent_key"] == (
        "length(dataset_independent_key) = 64 "
        "AND ltrim(dataset_independent_key, '0123456789abcdef') = ''"
    )
    assert checks["ck_reports_keys_complete"] == (
        "(key_version IS NULL) = (definition_key IS NULL) "
        "AND (key_version IS NULL) = (dataset_independent_key IS NULL)"
    )
    # The app finds a report's local-area report by this key alone, which
    # holds its own key version.
    index = _index("reports", "ix_reports_dataset_independent_key")
    assert not index.unique
    assert tuple(column.name for column in index.columns) == (
        "dataset_independent_key",
    )


@pytest.mark.parametrize("table_name", ["simulation_runs", "report_runs"])
def test_runs_record_whether_a_re_run_forced_them(table_name: str) -> None:
    """Every existing run, and every run the service writes without it, is unforced."""
    forced = V2_METADATA.tables[table_name].c.forced

    assert isinstance(forced.type, sa.Boolean)
    assert not forced.nullable
    assert forced.server_default is not None
    assert str(forced.server_default.arg) == "false"


@pytest.mark.parametrize(
    ("table_name", "index_name", "columns", "condition"),
    [
        (
            "simulation_runs",
            "uq_simulation_runs_unfailed_unforced_versions",
            (
                "simulation_id",
                "year",
                "tax_benefit_model_version_id",
                "country_package_version",
                "policyengine_version",
            ),
            UNFAILED_UNFORCED,
        ),
        (
            "report_runs",
            "uq_report_runs_unfailed_unforced_versions",
            ("report_id", "country_package_version", "policyengine_version"),
            f"budget_window_run_id IS NULL AND {UNFAILED_UNFORCED}",
        ),
    ],
)
def test_a_definition_has_one_unfailed_unforced_run_per_version_set(
    table_name: str, index_name: str, columns: tuple[str, ...], condition: str
) -> None:
    index = _index(table_name, index_name)

    assert index.unique
    assert tuple(column.name for column in index.columns) == columns
    assert str(index.dialect_options["postgresql"]["where"]) == condition
    assert str(index.dialect_options["sqlite"]["where"]) == condition


def test_user_report_run_associations_record_each_users_request_for_a_run() -> None:
    records = V2_METADATA.tables["user_report_run_associations"]

    assert {column.name for column in records.columns} == {
        "id",
        "created_at",
        "user_id",
        "report_run_id",
        "requested_at",
        "trigger",
    }
    for column_name in ("user_id", "report_run_id", "requested_at", "trigger"):
        assert not records.c[column_name].nullable, column_name
    assert records.c.requested_at.type.timezone
    assert records.c.requested_at.server_default is None
    assert records.c.trigger.type.name == "v2_report_run_trigger"
    foreign_keys = {
        key.parent.name: (key.column.table.name, key.ondelete)
        for key in records.foreign_keys
    }
    # A user's records go with the user; a run a user asked for stays.
    assert foreign_keys == {
        "user_id": ("users", "CASCADE"),
        "report_run_id": ("report_runs", "RESTRICT"),
    }
    assert _unique_constraints("user_report_run_associations") == {
        "uq_user_report_run_associations_user_id_report_run_id": (
            "user_id",
            "report_run_id",
        )
    }
    assert {
        tuple(column.name for column in index.columns) for index in records.indexes
    } == {("report_run_id",)}
    # A user creates a report or runs it again; a system re-run asks for no user.
    assert _checks("user_report_run_associations") == {
        "ck_user_report_run_associations_trigger": "trigger IN ('initial', 'manual')"
    }


@pytest.fixture
def sqlite_session() -> Iterator[Session]:
    engine = sa.create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


VALID_KEY = "4bb1299756cb0a89" * 4


@pytest.mark.parametrize(
    "definition_key",
    [
        VALID_KEY.upper(),
        VALID_KEY[:-1] + "A",
        VALID_KEY[:63],
        "g" * 64,
        " " * 64,
        "",
    ],
)
def test_sqlite_refuses_a_key_that_is_not_64_lowercase_hex_digits(
    sqlite_session: Session, definition_key: str
) -> None:
    """The unit tests' SQLite databases check a key's format as PostgreSQL does."""
    sqlite_session.add(
        Simulation(
            dataset_id=uuid4(),
            tax_benefit_model_version_id=uuid4(),
            key_version=1,
            definition_key=VALID_KEY,
        )
    )
    sqlite_session.commit()

    sqlite_session.add(
        Simulation(
            dataset_id=uuid4(),
            tax_benefit_model_version_id=uuid4(),
            key_version=1,
            definition_key=definition_key,
        )
    )
    with pytest.raises(IntegrityError, match="ck_simulations_definition_key"):
        sqlite_session.commit()


def _simulation_run(
    simulation_id: UUID,
    catalog_version_id: UUID,
    *,
    status: SimulationStatus = SimulationStatus.PENDING,
    forced: bool = False,
    policyengine_version: str = "4.2.0",
) -> SimulationRun:
    finished = status in {SimulationStatus.SUCCEEDED, SimulationStatus.FAILED}
    return SimulationRun(
        simulation_id=simulation_id,
        year=2026,
        tax_benefit_model_version_id=catalog_version_id,
        country_package_version="1.5.0",
        policyengine_version=policyengine_version,
        status=status,
        forced=forced,
        completed_at=datetime.now(UTC) if finished else None,
    )


def test_sqlite_refuses_a_second_unfailed_unforced_run_like_postgres(
    sqlite_session: Session,
) -> None:
    """Unit tests' SQLite databases keep the rule PostgreSQL enforces."""
    simulation_id = uuid4()
    catalog_version_id = uuid4()
    sqlite_session.add_all(
        [
            _simulation_run(
                simulation_id, catalog_version_id, status=SimulationStatus.FAILED
            ),
            _simulation_run(
                simulation_id, catalog_version_id, status=SimulationStatus.SUCCEEDED
            ),
            _simulation_run(simulation_id, catalog_version_id, forced=True),
            _simulation_run(
                simulation_id, catalog_version_id, policyengine_version="4.3.0"
            ),
        ]
    )
    sqlite_session.commit()

    sqlite_session.add(
        _simulation_run(
            simulation_id, catalog_version_id, status=SimulationStatus.RUNNING
        )
    )
    with pytest.raises(
        IntegrityError, match="UNIQUE constraint failed: simulation_runs"
    ):
        sqlite_session.commit()


def test_sqlite_lets_a_budget_window_name_one_report_run_per_year(
    sqlite_session: Session,
) -> None:
    report_id = uuid4()
    window_run_id = uuid4()

    def report_run(*, window_year: int | None) -> ReportRun:
        """Return a pending run of the report, in a window's year when given one."""
        return ReportRun(
            report_id=report_id,
            baseline_simulation_run_id=uuid4(),
            budget_window_run_id=None if window_year is None else window_run_id,
            year=window_year,
            country_package_version="1.5.0",
            policyengine_version="4.2.0",
        )

    sqlite_session.add_all(
        [
            report_run(window_year=2026),
            report_run(window_year=2027),
            report_run(window_year=None),
        ]
    )
    sqlite_session.commit()

    sqlite_session.add(report_run(window_year=None))
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed: report_runs"):
        sqlite_session.commit()
