"""Exercise the v2 catalog tables' revisions against disposable Postgres."""

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy import create_engine, inspect, text

from tests.fixtures.integration.alembic_v2 import (
    alembic_v2_config,
    disposable_v2_url,
    table_columns,
)

CATALOG_FORMAT_2_PARENT_REVISION = "fb1a3e40d3d6"
CATALOG_FORMAT_2_COLUMNS = {
    "tax_benefit_model_versions": ("catalog_format", "entities", "basic_inputs"),
    "variables": (
        "is_input_variable",
        "hidden_input",
        "module_name",
        "adds_parameter_path",
        "subtracts_parameter_path",
        "enum_values",
        "unit",
        "definition_period",
    ),
    "parameters": ("economy", "household"),
}


def _catalog_version_published_before_format_2(connection: sa.Connection) -> UUID:
    """Store a model version with one variable and one parameter; return its id."""
    model_id = uuid4()
    version_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO tax_benefit_models (id, name) "
            "VALUES (:model_id, 'catalog-format-probe')"
        ),
        {"model_id": model_id},
    )
    connection.execute(
        text(
            "INSERT INTO tax_benefit_model_versions "
            "(id, model_id, version, current_law_id, metadata_time_periods) "
            "VALUES (:version_id, :model_id, '0.0.1-probe', 1, '[2026]')"
        ),
        {"version_id": version_id, "model_id": model_id},
    )
    connection.execute(
        text(
            "INSERT INTO variables "
            "(id, name, entity, default_value, tax_benefit_model_version_id) "
            "VALUES (:variable_id, 'probe_income', 'person', '0', :version_id)"
        ),
        {"variable_id": uuid4(), "version_id": version_id},
    )
    connection.execute(
        text(
            "INSERT INTO parameters (id, name, tax_benefit_model_version_id) "
            "VALUES (:parameter_id, 'gov.probe.rate', :version_id)"
        ),
        {"parameter_id": uuid4(), "version_id": version_id},
    )
    return version_id


def _format_2_values(connection: sa.Connection, version_id: UUID) -> list[tuple]:
    """Return the format 2 columns of the version's model, variable and parameter."""
    rows = []
    for table_name, columns in CATALOG_FORMAT_2_COLUMNS.items():
        key = (
            "id"
            if table_name == "tax_benefit_model_versions"
            else "tax_benefit_model_version_id"
        )
        rows.append(
            tuple(
                connection.execute(
                    text(
                        f"SELECT {', '.join(columns)} FROM {table_name} "
                        f"WHERE {key} = :version_id"
                    ),
                    {"version_id": version_id},
                ).one()
            )
        )
    return rows


def test_catalog_format_2_columns_leave_earlier_versions_empty() -> None:
    """A version stored before catalog format 2 keeps its format 2 fields null.

    Upgrading adds the columns as nullable without writing to stored rows, and
    downgrading drops them and keeps every row.
    """
    config = alembic_v2_config()
    engine = create_engine(disposable_v2_url())
    version_id = None
    try:
        command.downgrade(config, CATALOG_FORMAT_2_PARENT_REVISION)
        for table_name, columns in CATALOG_FORMAT_2_COLUMNS.items():
            assert set(columns).isdisjoint(table_columns(engine, table_name))
        with engine.begin() as connection:
            version_id = _catalog_version_published_before_format_2(connection)

        command.upgrade(config, "head")

        for table_name, columns in CATALOG_FORMAT_2_COLUMNS.items():
            stored_columns = table_columns(engine, table_name)
            for column_name in columns:
                assert stored_columns[column_name]["nullable"]
                assert stored_columns[column_name]["default"] is None
        with engine.connect() as connection:
            assert _format_2_values(connection, version_id) == [
                (None, None, None),
                (None, None, None, None, None, None, None, None),
                (None, None),
            ]

        command.downgrade(config, CATALOG_FORMAT_2_PARENT_REVISION)

        for table_name, columns in CATALOG_FORMAT_2_COLUMNS.items():
            assert set(columns).isdisjoint(table_columns(engine, table_name))
        with engine.connect() as connection:
            counts = connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM variables "
                    "WHERE tax_benefit_model_version_id = :version_id), "
                    "(SELECT count(*) FROM parameters "
                    "WHERE tax_benefit_model_version_id = :version_id)"
                ),
                {"version_id": version_id},
            ).one()
        assert tuple(counts) == (1, 1)
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM tax_benefit_models WHERE name = 'catalog-format-probe'"
                )
            )
        command.upgrade(config, "head")
        engine.dispose()


PARAMETER_TREE_PARENT_REVISION = "e86f19a6c4da"


def test_parameter_tree_table_is_created_empty_and_dropped_without_data_loss() -> None:
    """The parameter tree revision creates an empty table and downgrades cleanly.

    The revision writes no rows: catalog publication writes each version's
    tree. A tree row is deleted with its version or its parameter, and
    downgrading drops the table while every catalog row stays.
    """
    config = alembic_v2_config()
    engine = create_engine(disposable_v2_url())
    try:
        command.downgrade(config, PARAMETER_TREE_PARENT_REVISION)
        assert "parameter_tree_children" not in inspect(engine).get_table_names()
        with engine.begin() as connection:
            version_id = _catalog_version_published_before_format_2(connection)

        command.upgrade(config, "head")

        indexes = {
            index["name"]: (index["column_names"], index["unique"])
            for index in inspect(engine).get_indexes("parameter_tree_children")
        }
        assert indexes["ix_parameter_tree_children_listing"] == (
            ["tax_benefit_model_version_id", "parent_path", "position"],
            True,
        )
        assert indexes["ix_parameter_tree_children_reform_listing"] == (
            ["tax_benefit_model_version_id", "parent_path", "reform_position"],
            True,
        )
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM parameter_tree_children")
                ).scalar_one()
                == 0
            )
            parameter_id = connection.execute(
                text(
                    "SELECT id FROM parameters "
                    "WHERE tax_benefit_model_version_id = :version_id"
                ),
                {"version_id": version_id},
            ).scalar_one()
            for path, parent, position, child_type, child_count, reference in (
                ("gov", "", 0, "node", 1, None),
                ("gov.probe", "gov", 0, "node", 1, None),
                ("gov.probe.rate", "gov.probe", 0, "parameter", None, parameter_id),
            ):
                connection.execute(
                    text(
                        "INSERT INTO parameter_tree_children (id, "
                        "tax_benefit_model_version_id, parent_path, path, position, "
                        "label, child_type, child_count, parameter_id) VALUES "
                        "(:id, :version_id, :parent, :path, :position, :path, "
                        ":child_type, :child_count, :parameter_id)"
                    ),
                    {
                        "id": uuid4(),
                        "version_id": version_id,
                        "parent": parent,
                        "path": path,
                        "position": position,
                        "child_type": child_type,
                        "child_count": child_count,
                        "parameter_id": reference,
                    },
                )
            with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO parameter_tree_children (id, "
                        "tax_benefit_model_version_id, parent_path, path, position, "
                        "label, child_type) VALUES (:id, :version_id, 'gov', "
                        "'gov.other', 0, 'Other', 'node')"
                    ),
                    {"id": uuid4(), "version_id": version_id},
                )
            connection.execute(
                text("DELETE FROM parameters WHERE id = :parameter_id"),
                {"parameter_id": parameter_id},
            )
            assert connection.execute(
                text("SELECT path FROM parameter_tree_children ORDER BY path")
            ).scalars().all() == ["gov", "gov.probe"]

        command.downgrade(config, PARAMETER_TREE_PARENT_REVISION)

        assert "parameter_tree_children" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM variables "
                        "WHERE tax_benefit_model_version_id = :version_id"
                    ),
                    {"version_id": version_id},
                ).scalar_one()
                == 1
            )
    finally:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM tax_benefit_models WHERE name = 'catalog-format-probe'"
                )
            )
        engine.dispose()


PARAMETER_SEARCH_FILE_PARENT_REVISION = "3869eb814a90"


def test_parameter_search_file_table_is_created_empty_and_dropped_without_loss() -> (
    None
):
    """The search file revision creates an empty table and downgrades cleanly.

    The revision writes no rows: catalog publication writes each version's
    file. A version holds at most one file, the file is deleted with its
    version, and downgrading drops the table while every catalog row stays.
    """
    config = alembic_v2_config()
    engine = create_engine(disposable_v2_url())
    try:
        command.downgrade(config, PARAMETER_SEARCH_FILE_PARENT_REVISION)
        assert "parameter_search_files" not in inspect(engine).get_table_names()
        with engine.begin() as connection:
            version_id = _catalog_version_published_before_format_2(connection)

        command.upgrade(config, "head")

        insert_file = text(
            "INSERT INTO parameter_search_files (id, tax_benefit_model_version_id, "
            "file_format, compressed_content, content_sha256, uncompressed_size, "
            "compressed_size) VALUES (:id, :version_id, 1, :content, :sha, 2, 22)"
        )
        file_values = {
            "version_id": version_id,
            "content": b"\x1f\x8b compressed bytes",
            "sha": "0" * 64,
        }
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM parameter_search_files")
                ).scalar_one()
                == 0
            )
            connection.execute(insert_file, {"id": uuid4(), **file_values})
            with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
                connection.execute(insert_file, {"id": uuid4(), **file_values})
            assert (
                connection.execute(
                    text(
                        "SELECT compressed_content FROM parameter_search_files "
                        "WHERE tax_benefit_model_version_id = :version_id"
                    ),
                    {"version_id": version_id},
                ).scalar_one()
                == file_values["content"]
            )

        command.downgrade(config, PARAMETER_SEARCH_FILE_PARENT_REVISION)

        assert "parameter_search_files" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM variables "
                        "WHERE tax_benefit_model_version_id = :version_id"
                    ),
                    {"version_id": version_id},
                ).scalar_one()
                == 1
            )

        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(insert_file, {"id": uuid4(), **file_values})
            connection.execute(
                text("DELETE FROM tax_benefit_model_versions WHERE id = :version_id"),
                {"version_id": version_id},
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM parameter_search_files")
                ).scalar_one()
                == 0
            )
    finally:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM tax_benefit_models WHERE name = 'catalog-format-probe'"
                )
            )
        engine.dispose()


CATALOG_PRUNING_MARKER_PARENT_REVISION = "c614b6bcccfc"


def _pruning_marker(connection: sa.Connection, version_id: UUID) -> object:
    return connection.execute(
        text(
            "SELECT catalog_values_pruned_at FROM tax_benefit_model_versions "
            "WHERE id = :version_id"
        ),
        {"version_id": version_id},
    ).scalar_one()


def test_catalog_pruning_marker_is_added_null_and_dropped_without_loss() -> None:
    """The marker revision adds a null column and downgrades cleanly.

    A stored version starts unpruned (null), the column takes a timestamp,
    and downgrading drops only the column: the version and its rows stay.
    Upgrading again gives every version a null marker.
    """
    config = alembic_v2_config()
    engine = create_engine(disposable_v2_url())
    try:
        command.downgrade(config, CATALOG_PRUNING_MARKER_PARENT_REVISION)
        assert "catalog_values_pruned_at" not in table_columns(
            engine, "tax_benefit_model_versions"
        )
        with engine.begin() as connection:
            version_id = _catalog_version_published_before_format_2(connection)

        command.upgrade(config, "head")

        with engine.begin() as connection:
            assert _pruning_marker(connection, version_id) is None
            connection.execute(
                text(
                    "UPDATE tax_benefit_model_versions "
                    "SET catalog_values_pruned_at = now() WHERE id = :version_id"
                ),
                {"version_id": version_id},
            )
            assert _pruning_marker(connection, version_id) is not None

        command.downgrade(config, CATALOG_PRUNING_MARKER_PARENT_REVISION)

        assert "catalog_values_pruned_at" not in table_columns(
            engine, "tax_benefit_model_versions"
        )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT version FROM tax_benefit_model_versions "
                        "WHERE id = :version_id"
                    ),
                    {"version_id": version_id},
                ).scalar_one()
                == "0.0.1-probe"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM parameters "
                        "WHERE tax_benefit_model_version_id = :version_id"
                    ),
                    {"version_id": version_id},
                ).scalar_one()
                == 1
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert _pruning_marker(connection, version_id) is None
    finally:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM tax_benefit_models WHERE name = 'catalog-format-probe'"
                )
            )
        engine.dispose()
