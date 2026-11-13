"""Identical requests end on the same simulations, reports and runs.

The simulation service finds each simulation and report by its key, and joins
a run on the same versions that hasn't failed, with ``INSERT ... ON CONFLICT
DO NOTHING`` against the indexes the shared-report revision adds; a forced
re-run is an extra run that nothing joins. The Public API records each user's
request for a report run. Each statement runs as the role that runs it in
staging and production, holding only its declared privileges
(``policyengine_api/data/v2/privileges.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.pool import NullPool

from policyengine_api.constants import REPO
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    PublicApiRows,
    insert_public_api_rows,
    insert_row,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection

# SHA-256 digests, as the simulation service computes keys.
NATIONAL_KEY = "4bb1299756cb0a89" * 4
LOCAL_AREA_KEY = "907455a2702b0559" * 4
DATASET_INDEPENDENT_KEY = "bcabc98b4e0d3eff" * 4
NEWER_VERSIONS = {"country_package_version": "1.1.0", "policyengine_version": "4.1.0"}

# What the simulation service will send: a new row, or nothing when one with
# the same key, or an unfailed unforced run on the same versions, exists.
FIND_OR_CREATE_SIMULATION = (
    "INSERT INTO simulations (id, simulation_type, dataset_id, "
    "tax_benefit_model_version_id, year, key_version, definition_key) "
    "VALUES (:id, 'economy', :dataset_id, :version_id, 2026, 1, :key) "
    "ON CONFLICT (key_version, definition_key) DO NOTHING RETURNING id"
)
FIND_OR_CREATE_REPORT = (
    "INSERT INTO reports (id, label, country, tax_benefit_model_id, year, inputs, "
    "key_version, definition_key, dataset_independent_key) "
    "VALUES (:id, 'Report', 'us', :model_id, 2026, '{}', 1, :key, "
    ":dataset_independent_key) "
    "ON CONFLICT (key_version, definition_key) DO NOTHING RETURNING id"
)
FIND_OR_CREATE_SIMULATION_RUN = (
    "INSERT INTO simulation_runs (id, simulation_id, year, "
    "tax_benefit_model_version_id, country_package_version, "
    "policyengine_version, status, forced) "
    "VALUES (:id, :simulation_id, :year, :version_id, :country_package_version, "
    ":policyengine_version, 'pending', :forced) "
    "ON CONFLICT (simulation_id, year, tax_benefit_model_version_id, "
    "country_package_version, policyengine_version) "
    "WHERE status <> 'failed' AND NOT forced DO NOTHING RETURNING id"
)
FIND_OR_CREATE_REPORT_RUN = (
    "INSERT INTO report_runs (id, report_id, baseline_simulation_run_id, "
    "country_package_version, policyengine_version, status, trigger, forced) "
    "VALUES (:id, :report_id, :baseline_run_id, :country_package_version, "
    ":policyengine_version, 'pending', 'initial', :forced) "
    "ON CONFLICT (report_id, country_package_version, policyengine_version) "
    "WHERE budget_window_run_id IS NULL AND status <> 'failed' AND NOT forced "
    "DO NOTHING RETURNING id"
)
RECORD_REQUEST = (
    "INSERT INTO user_report_run_associations (id, user_id, report_run_id, "
    "requested_at, trigger) VALUES (:id, :user_id, :report_run_id, now(), :trigger)"
)


@pytest.fixture
def connection(disposable_v2_database_url, managed_v2_roles) -> Iterator[Connection]:
    """Yield a connection at head whose writes are rolled back after the test.

    It connects as the disposable database's superuser, which owns every
    table; ``_act_as`` switches it to one managed role and ``_act_as_owner``
    back.
    """
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    try:
        with engine.connect() as database_connection:
            transaction = database_connection.begin()
            try:
                yield database_connection
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def public_api_rows(connection: Connection) -> PublicApiRows:
    return insert_public_api_rows(connection)


def _act_as(connection: Connection, role: str) -> None:
    quoted_role = connection.dialect.identifier_preparer.quote(role)
    connection.execute(text(f"SET LOCAL ROLE {quoted_role}"))


def _act_as_owner(connection: Connection) -> None:
    connection.execute(text("RESET ROLE"))


def _inserted_id(
    connection: Connection, statement: str, **values: object
) -> UUID | None:
    """Run an ``INSERT ... RETURNING id``; return the new row's ID, or None."""
    return connection.execute(text(statement), values).scalar_one_or_none()


def _refused(
    connection: Connection,
    statement: str,
    error: type[Exception] = IntegrityError,
    match: str | None = None,
    **values: object,
) -> None:
    with refused(connection, error, match=match):
        connection.execute(text(statement), values)


def _simulation(
    connection: Connection, public_api_rows: PublicApiRows, key: str | None = None
) -> UUID:
    """Create an economy simulation of 2026, keyed when ``key`` is given."""
    simulation_id = uuid4()
    insert_row(
        connection,
        "simulations",
        id=simulation_id,
        simulation_type="economy",
        dataset_id=public_api_rows.dataset_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
        key_version=None if key is None else 1,
        definition_key=key,
    )
    return simulation_id


def _simulation_run(  # noqa: PLR0913  # the simulation, then each part of its run
    connection: Connection,
    public_api_rows: PublicApiRows,
    simulation_id: UUID,
    *,
    year: int = 2026,
    versions: dict[str, str] = RUN_VERSIONS,
    forced: bool = False,
) -> UUID | None:
    """Find or create the simulation's run; return its ID if this call created it."""
    return _inserted_id(
        connection,
        FIND_OR_CREATE_SIMULATION_RUN,
        id=uuid4(),
        simulation_id=simulation_id,
        year=year,
        version_id=public_api_rows.version_id,
        forced=forced,
        **versions,
    )


def _report(connection: Connection, public_api_rows: PublicApiRows) -> UUID:
    report_id = uuid4()
    insert_row(
        connection,
        "reports",
        id=report_id,
        label="Report",
        country="us",
        tax_benefit_model_id=public_api_rows.model_id,
        year=2026,
        inputs="{}",
    )
    return report_id


def _report_run(
    connection: Connection,
    report_id: UUID,
    baseline_run_id: UUID,
    *,
    versions: dict[str, str] = RUN_VERSIONS,
    forced: bool = False,
) -> UUID | None:
    """Find or create the report's run; return its ID if this call created it."""
    return _inserted_id(
        connection,
        FIND_OR_CREATE_REPORT_RUN,
        id=uuid4(),
        report_id=report_id,
        baseline_run_id=baseline_run_id,
        forced=forced,
        **versions,
    )


def _fail(connection: Connection, table: str, run_id: UUID) -> None:
    connection.execute(
        text(
            f"UPDATE {table} SET status = 'failed', error_message = 'failed', "
            "completed_at = now(), updated_at = now() WHERE id = :id"
        ),
        {"id": run_id},
    )


def _user(connection: Connection) -> UUID:
    user_id = uuid4()
    insert_row(
        connection, "users", id=user_id, user_type="standard", primary_country="us"
    )
    return user_id


def test_identical_keys_name_one_simulation_and_one_report(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    _act_as(connection, managed_v2_roles.simulation_service)

    simulation_id = _inserted_id(
        connection,
        FIND_OR_CREATE_SIMULATION,
        id=uuid4(),
        dataset_id=public_api_rows.dataset_id,
        version_id=public_api_rows.version_id,
        key=NATIONAL_KEY,
    )
    joined_simulation = _inserted_id(
        connection,
        FIND_OR_CREATE_SIMULATION,
        id=uuid4(),
        dataset_id=public_api_rows.dataset_id,
        version_id=public_api_rows.version_id,
        key=NATIONAL_KEY,
    )
    national_report = _inserted_id(
        connection,
        FIND_OR_CREATE_REPORT,
        id=uuid4(),
        model_id=public_api_rows.model_id,
        key=NATIONAL_KEY,
        dataset_independent_key=DATASET_INDEPENDENT_KEY,
    )
    joined_report = _inserted_id(
        connection,
        FIND_OR_CREATE_REPORT,
        id=uuid4(),
        model_id=public_api_rows.model_id,
        key=NATIONAL_KEY,
        dataset_independent_key=DATASET_INDEPENDENT_KEY,
    )
    # The local-area report is its own report, linked by the shared key.
    local_area_report = _inserted_id(
        connection,
        FIND_OR_CREATE_REPORT,
        id=uuid4(),
        model_id=public_api_rows.model_id,
        key=LOCAL_AREA_KEY,
        dataset_independent_key=DATASET_INDEPENDENT_KEY,
    )

    assert simulation_id is not None
    assert joined_simulation is None
    assert national_report is not None
    assert joined_report is None
    assert local_area_report not in {None, national_report}
    found = connection.execute(
        text(
            "SELECT id FROM simulations WHERE key_version = 1 AND definition_key = :key"
        ),
        {"key": NATIONAL_KEY},
    ).scalar_one()
    assert found == simulation_id
    linked = connection.execute(
        text(
            "SELECT count(*) FROM reports WHERE key_version = 1 "
            "AND dataset_independent_key = :key"
        ),
        {"key": DATASET_INDEPENDENT_KEY},
    ).scalar_one()
    assert linked == 2
    # Rows from before the keys, and a later key format, stay apart.
    assert _simulation(connection, public_api_rows) != _simulation(
        connection, public_api_rows
    )
    insert_row(
        connection,
        "simulations",
        id=uuid4(),
        simulation_type="economy",
        dataset_id=public_api_rows.dataset_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
        key_version=2,
        definition_key=NATIONAL_KEY,
    )


@pytest.mark.parametrize(
    ("table", "key_columns"),
    [
        ("simulations", {"key_version": 1, "definition_key": NATIONAL_KEY.upper()}),
        ("simulations", {"key_version": 1, "definition_key": NATIONAL_KEY[:63]}),
        # Lowercase, 64 characters, but not hexadecimal.
        ("simulations", {"key_version": 1, "definition_key": "g" * 64}),
        ("simulations", {"key_version": 0, "definition_key": NATIONAL_KEY}),
        ("simulations", {"key_version": None, "definition_key": NATIONAL_KEY}),
        ("simulations", {"key_version": 1, "definition_key": None}),
        (
            "reports",
            {
                "key_version": 1,
                "definition_key": NATIONAL_KEY,
                "dataset_independent_key": None,
            },
        ),
        (
            "reports",
            {
                "key_version": None,
                "definition_key": None,
                "dataset_independent_key": DATASET_INDEPENDENT_KEY,
            },
        ),
        (
            "reports",
            {
                "key_version": 1,
                "definition_key": NATIONAL_KEY,
                "dataset_independent_key": DATASET_INDEPENDENT_KEY.upper(),
            },
        ),
    ],
)
def test_a_malformed_or_incomplete_key_is_refused(
    connection: Connection,
    public_api_rows: PublicApiRows,
    table: str,
    key_columns: dict[str, object],
) -> None:
    columns: dict[str, object] = (
        {
            "simulation_type": "economy",
            "dataset_id": public_api_rows.dataset_id,
            "tax_benefit_model_version_id": public_api_rows.version_id,
        }
        if table == "simulations"
        else {
            "label": "Report",
            "country": "us",
            "tax_benefit_model_id": public_api_rows.model_id,
            "inputs": "{}",
        }
    )
    columns |= {"id": uuid4(), "year": 2026, **key_columns}

    with refused(connection, IntegrityError, match="violates check constraint"):
        insert_row(connection, table, **columns)


def test_a_simulation_has_one_unfailed_unforced_run_per_version_set(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _simulation(connection, public_api_rows, NATIONAL_KEY)
    _act_as(connection, managed_v2_roles.simulation_service)

    first_run = _simulation_run(connection, public_api_rows, simulation_id)
    joined = _simulation_run(connection, public_api_rows, simulation_id)
    forced_run = _simulation_run(
        connection, public_api_rows, simulation_id, forced=True
    )
    second_forced_run = _simulation_run(
        connection, public_api_rows, simulation_id, forced=True
    )
    newer_versions_run = _simulation_run(
        connection, public_api_rows, simulation_id, versions=NEWER_VERSIONS
    )
    other_year_run = _simulation_run(
        connection, public_api_rows, simulation_id, year=2027
    )

    assert first_run is not None
    assert joined is None
    assert None not in {forced_run, second_forced_run, newer_versions_run}
    assert other_year_run is not None
    # Today's plain INSERT of a second run on the same versions is refused.
    _refused(
        connection,
        "INSERT INTO simulation_runs (id, simulation_id, year, "
        "tax_benefit_model_version_id, country_package_version, "
        "policyengine_version, status) VALUES (:id, :simulation_id, 2026, "
        ":version_id, :country_package_version, :policyengine_version, 'pending')",
        match="uq_simulation_runs_unfailed_unforced_versions",
        id=uuid4(),
        simulation_id=simulation_id,
        version_id=public_api_rows.version_id,
        **RUN_VERSIONS,
    )

    # A failed run never counts: the next request creates a new run.
    _act_as(connection, managed_v2_roles.modal_worker)
    _fail(connection, "simulation_runs", first_run)
    _act_as(connection, managed_v2_roles.simulation_service)
    after_failure = _simulation_run(connection, public_api_rows, simulation_id)
    assert after_failure not in {None, first_run}
    # The failed run can't count again while the new one hasn't failed.
    _act_as(connection, managed_v2_roles.modal_worker)
    _refused(
        connection,
        "UPDATE simulation_runs SET status = 'running' WHERE id = :id",
        match="uq_simulation_runs_unfailed_unforced_versions",
        id=first_run,
    )


def test_a_report_has_one_unfailed_unforced_run_per_version_set_outside_windows(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _simulation(connection, public_api_rows, NATIONAL_KEY)
    report_id = _report(connection, public_api_rows)
    _act_as(connection, managed_v2_roles.simulation_service)
    baseline_run_id = _simulation_run(connection, public_api_rows, simulation_id)
    assert baseline_run_id is not None

    first_run = _report_run(connection, report_id, baseline_run_id)
    joined = _report_run(connection, report_id, baseline_run_id)
    forced_run = _report_run(connection, report_id, baseline_run_id, forced=True)
    newer_versions_run = _report_run(
        connection, report_id, baseline_run_id, versions=NEWER_VERSIONS
    )
    # Each window run names a report run per year on the same versions.
    for window_run_id in (uuid4(), uuid4()):
        insert_row(
            connection,
            "budget_window_runs",
            id=window_run_id,
            report_id=report_id,
            tax_benefit_model_version_id=public_api_rows.version_id,
            trigger="initial",
            recalculate=False,
            status="pending",
        )
        insert_row(
            connection,
            "report_runs",
            id=uuid4(),
            report_id=report_id,
            budget_window_run_id=window_run_id,
            year=2026,
            baseline_simulation_run_id=baseline_run_id,
            status="pending",
            trigger="initial",
            **RUN_VERSIONS,
        )

    assert first_run is not None
    assert joined is None
    assert None not in {forced_run, newer_versions_run}
    _act_as(connection, managed_v2_roles.modal_worker)
    _fail(connection, "report_runs", first_run)
    _act_as(connection, managed_v2_roles.simulation_service)
    assert _report_run(connection, report_id, baseline_run_id) not in {
        None,
        first_run,
    }


def test_no_simulation_role_changes_a_rows_key_or_a_runs_forced_marker(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _simulation(connection, public_api_rows, NATIONAL_KEY)
    report_id = _report(connection, public_api_rows)
    _act_as(connection, managed_v2_roles.simulation_service)
    run_id = _simulation_run(connection, public_api_rows, simulation_id)
    assert run_id is not None
    report_run_id = _report_run(connection, report_id, run_id)

    for role in (
        managed_v2_roles.simulation_service,
        managed_v2_roles.modal_worker,
    ):
        _act_as(connection, role)
        for statement, row_id in (
            (
                "UPDATE simulations SET definition_key = NULL WHERE id = :id",
                simulation_id,
            ),
            ("UPDATE reports SET key_version = 1 WHERE id = :id", report_id),
            ("UPDATE simulation_runs SET forced = true WHERE id = :id", run_id),
            ("UPDATE report_runs SET forced = true WHERE id = :id", report_run_id),
        ):
            _refused(
                connection,
                statement,
                ProgrammingError,
                match="permission denied",
                id=row_id,
            )


def test_the_public_api_records_each_users_request_for_a_report_run(
    connection: Connection, managed_v2_roles, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _simulation(connection, public_api_rows, NATIONAL_KEY)
    report_id = _report(connection, public_api_rows)
    first_user, second_user, third_user = (_user(connection) for _ in range(3))
    _act_as(connection, managed_v2_roles.simulation_service)
    baseline_run_id = _simulation_run(connection, public_api_rows, simulation_id)
    report_run_id = _report_run(connection, report_id, baseline_run_id)
    _act_as(connection, managed_v2_roles.runtime)

    first_record, second_record = uuid4(), uuid4()
    connection.execute(
        text(RECORD_REQUEST),
        {
            "id": first_record,
            "user_id": first_user,
            "report_run_id": report_run_id,
            "trigger": "initial",
        },
    )
    # A second user who joins the same run gets a record of their own.
    connection.execute(
        text(RECORD_REQUEST),
        {
            "id": second_record,
            "user_id": second_user,
            "report_run_id": report_run_id,
            "trigger": "manual",
        },
    )
    requesters = connection.execute(
        text(
            "SELECT user_id FROM user_report_run_associations "
            "WHERE report_run_id = :report_run_id ORDER BY trigger"
        ),
        {"report_run_id": report_run_id},
    ).scalars()
    assert list(requesters) == [first_user, second_user]
    _refused(
        connection,
        RECORD_REQUEST,
        match="uq_user_report_run_associations_user_id_report_run_id",
        id=uuid4(),
        user_id=first_user,
        report_run_id=report_run_id,
        trigger="manual",
    )
    # A system re-run is nobody's request.
    _refused(
        connection,
        RECORD_REQUEST,
        match="ck_user_report_run_associations_trigger",
        id=uuid4(),
        user_id=third_user,
        report_run_id=report_run_id,
        trigger="system",
    )
    _refused(
        connection,
        "UPDATE user_report_run_associations SET requested_at = now() WHERE id = :id",
        ProgrammingError,
        match="permission denied",
        id=first_record,
    )
    deleted = connection.execute(
        text("DELETE FROM user_report_run_associations WHERE id = :id RETURNING id"),
        {"id": second_record},
    ).scalar_one()
    assert deleted == second_record

    for role in (managed_v2_roles.simulation_service, managed_v2_roles.modal_worker):
        _act_as(connection, role)
        _refused(
            connection,
            "SELECT count(*) FROM user_report_run_associations",
            ProgrammingError,
            match="permission denied",
        )

    # A run a user asked for stays; the user's records go with the user.
    _act_as_owner(connection)
    _refused(
        connection,
        "DELETE FROM report_runs WHERE id = :id",
        match="fk_user_report_run_associations_report_run_id_report_runs",
        id=report_run_id,
    )
    connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": first_user})
    remaining = connection.execute(
        text("SELECT count(*) FROM user_report_run_associations")
    ).scalar_one()
    assert remaining == 0
