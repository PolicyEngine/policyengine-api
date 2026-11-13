"""Check the shared-report revision against disposable Postgres.

Revision 94dc43079186 lets identical requests share simulations, reports and
runs. It adds nullable key columns, unique on the key and its version, to
``simulations`` and ``reports`` (and the key shared across datasets to
``reports``, indexed); a ``forced`` marker, false by default, to
``simulation_runs`` and ``report_runs``; a partial unique index on each run
table that allows one unfailed, unforced run per definition and version set;
a .py version on ``budget_window_runs``, with a partial unique index allowing
one unfailed, unrecalculated window run per report and version set; and the
``user_report_run_associations`` table. It changes nothing else, and
its downgrade removes exactly those.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql

from tests.fixtures.integration.alembic_v2 import alembic_v2_config, disposable_v2_url

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

SHARED_REPORTS_PREVIOUS_REVISION = "1e1e3f079f2c"
SHARED_REPORTS_REVISION = "94dc43079186"

KEY_FORMAT_CHECKS = {
    "simulations": {
        "ck_simulations_key_version",
        "ck_simulations_definition_key",
        "ck_simulations_keys_complete",
    },
    "reports": {
        "ck_reports_key_version",
        "ck_reports_definition_key",
        "ck_reports_dataset_independent_key",
        "ck_reports_keys_complete",
    },
}
UNFAILED_UNFORCED = "((status <> 'failed'::v2_{status_type}) AND (NOT forced))"


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Yield an engine on the disposable database, and leave it at head."""
    database_engine = create_engine(disposable_v2_url())
    try:
        yield database_engine
    finally:
        command.upgrade(alembic_v2_config(), "head")
        database_engine.dispose()


def _schema_shape(engine: Engine) -> dict[str, dict[str, Any]]:
    """Reflect every table's columns, keys, indexes (with conditions) and checks."""
    inspector = inspect(engine)
    return {
        table_name: {
            "columns": {
                column["name"]: (
                    column["type"].compile(dialect=postgresql.dialect()),
                    column["nullable"],
                    column.get("default"),
                )
                for column in inspector.get_columns(table_name)
            },
            "foreign_keys": sorted(
                (
                    key["name"],
                    tuple(key["constrained_columns"]),
                    key["referred_table"],
                    key["options"].get("ondelete"),
                )
                for key in inspector.get_foreign_keys(table_name)
            ),
            "unique_constraints": {
                unique["name"]: tuple(unique["column_names"])
                for unique in inspector.get_unique_constraints(table_name)
            },
            "indexes": {
                index["name"]: (
                    tuple(index["column_names"]),
                    index["unique"],
                    index.get("dialect_options", {}).get("postgresql_where"),
                )
                for index in inspector.get_indexes(table_name)
                # A unique constraint's own index is listed with the constraints.
                if "duplicates_constraint" not in index
            },
            "checks": {
                check["name"]: check["sqltext"]
                for check in inspector.get_check_constraints(table_name)
            },
        }
        for table_name in inspector.get_table_names(schema="public")
        if table_name != "alembic_version"
    }


def _added(
    parent: dict[str, Any], revision: dict[str, Any], part: str
) -> dict[str, Any]:
    """Return what the revision added to a part of a table; check it kept the rest."""
    assert set(parent[part]) <= set(revision[part]), part
    for name in parent[part]:
        assert revision[part][name] == parent[part][name], (part, name)
    return {
        name: value
        for name, value in revision[part].items()
        if name not in parent[part]
    }


def test_shared_reports_revision_changes_only_its_tables_and_downgrades_exactly(
    engine: Engine,
) -> None:
    config = alembic_v2_config()
    command.upgrade(config, "head")
    command.downgrade(config, SHARED_REPORTS_PREVIOUS_REVISION)
    parent = _schema_shape(engine)
    command.upgrade(config, SHARED_REPORTS_REVISION)
    revision = _schema_shape(engine)

    assert set(revision) - set(parent) == {"user_report_run_associations"}
    assert sorted(
        table_name
        for table_name in parent
        if revision[table_name] != parent[table_name]
    ) == [
        "budget_window_runs",
        "report_runs",
        "reports",
        "simulation_runs",
        "simulations",
    ]

    for table_name in ("simulations", "reports"):
        parent_table, revision_table = parent[table_name], revision[table_name]
        added_columns = _added(parent_table, revision_table, "columns")
        expected_columns = {
            "key_version": ("INTEGER", True, None),
            "definition_key": ("VARCHAR(64)", True, None),
        }
        if table_name == "reports":
            expected_columns["dataset_independent_key"] = ("VARCHAR(64)", True, None)
        assert added_columns == expected_columns
        assert _added(parent_table, revision_table, "unique_constraints") == {
            f"uq_{table_name}_key_version_definition_key": (
                "key_version",
                "definition_key",
            )
        }
        assert (
            set(_added(parent_table, revision_table, "checks"))
            == (KEY_FORMAT_CHECKS[table_name])
        )
        assert _added(parent_table, revision_table, "indexes") == (
            {
                "ix_reports_dataset_independent_key": (
                    ("dataset_independent_key",),
                    False,
                    None,
                )
            }
            if table_name == "reports"
            else {}
        )
        assert revision_table["foreign_keys"] == parent_table["foreign_keys"]

    for table_name, status_type, index_name, columns, window_condition in (
        (
            "simulation_runs",
            "simulation_status",
            "uq_simulation_runs_unfailed_unforced_versions",
            (
                "simulation_id",
                "year",
                "tax_benefit_model_version_id",
                "country_package_version",
                "policyengine_version",
            ),
            None,
        ),
        (
            "report_runs",
            "report_run_status",
            "uq_report_runs_unfailed_unforced_versions",
            ("report_id", "country_package_version", "policyengine_version"),
            "(budget_window_run_id IS NULL)",
        ),
    ):
        parent_table, revision_table = parent[table_name], revision[table_name]
        assert _added(parent_table, revision_table, "columns") == {
            "forced": ("BOOLEAN", False, "false")
        }
        unfailed_unforced = UNFAILED_UNFORCED.format(status_type=status_type)
        condition = (
            unfailed_unforced
            if window_condition is None
            else f"({window_condition} AND {unfailed_unforced.removeprefix('(')}"
        )
        assert _added(parent_table, revision_table, "indexes") == {
            index_name: (columns, True, condition)
        }
        for part in ("unique_constraints", "checks", "foreign_keys"):
            assert revision_table[part] == parent_table[part], (table_name, part)

    # A window run records its .py version, and recalculate marks it forced.
    parent_windows, revision_windows = (
        parent["budget_window_runs"],
        revision["budget_window_runs"],
    )
    assert _added(parent_windows, revision_windows, "columns") == {
        "policyengine_version": ("VARCHAR(128)", True, None)
    }
    assert _added(parent_windows, revision_windows, "indexes") == {
        "uq_budget_window_runs_unfailed_unforced_versions": (
            ("report_id", "tax_benefit_model_version_id", "policyengine_version"),
            True,
            "((status <> 'failed'::v2_report_run_status) AND (NOT recalculate))",
        )
    }
    for part in ("unique_constraints", "checks", "foreign_keys"):
        assert revision_windows[part] == parent_windows[part], part

    records = revision["user_report_run_associations"]
    assert records["columns"] == {
        "id": ("UUID", False, None),
        "created_at": ("TIMESTAMP WITH TIME ZONE", False, "now()"),
        "user_id": ("UUID", False, None),
        "report_run_id": ("UUID", False, None),
        "requested_at": ("TIMESTAMP WITH TIME ZONE", False, None),
        # The report runs' type, not another one.
        "trigger": ("v2_report_run_trigger", False, None),
    }
    assert records["foreign_keys"] == [
        (
            "fk_user_report_run_associations_report_run_id_report_runs",
            ("report_run_id",),
            "report_runs",
            "RESTRICT",
        ),
        (
            "fk_user_report_run_associations_user_id_users",
            ("user_id",),
            "users",
            "CASCADE",
        ),
    ]
    assert records["unique_constraints"] == {
        "uq_user_report_run_associations_user_id_report_run_id": (
            "user_id",
            "report_run_id",
        )
    }
    assert records["indexes"] == {
        "ix_user_report_run_associations_report_run_id": (
            ("report_run_id",),
            False,
            None,
        )
    }
    assert set(records["checks"]) == {"ck_user_report_run_associations_trigger"}

    command.downgrade(config, SHARED_REPORTS_PREVIOUS_REVISION)
    assert _schema_shape(engine) == parent
