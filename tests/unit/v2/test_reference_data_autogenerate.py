"""Tests for generated-only declarative application-data migrations."""

from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations, ops
import pytest
import sqlalchemy as sa

from policyengine_api.data.v2.models import V2_METADATA
from policyengine_api.data.v2.reference_data import (
    REFERENCE_DATA,
    REFERENCE_DATA_FORMAT_VERSION,
    ReferenceDataDeclarationError,
    ReferenceRow,
    ReferenceTable,
)
from policyengine_api.data.v2.reference_data_autogenerate import (
    ReferenceDataMigrationError,
    ReferenceRowChangeOp,
    _render_reference_row_change,
    compare_reference_data,
    order_generated_operations,
)
from policyengine_api.data.v2.table_inventory import EXPECTED_V2_TABLES


def test_declaration_has_stable_scoped_natural_keys_and_wire_values() -> None:
    assert REFERENCE_DATA_FORMAT_VERSION == 1
    assert [table.table_name for table in REFERENCE_DATA] == [
        "tax_benefit_models",
        "tax_benefit_model_versions",
    ]
    for table in REFERENCE_DATA:
        assert table.managed_prefix_column in table.key_columns
        for row in table.rows:
            assert tuple(row.key) == table.key_columns
            assert row.key[table.managed_prefix_column].startswith(table.managed_prefix)


def test_declaration_rejects_unknown_tables_duplicate_keys_and_unsafe_values() -> None:
    row = ReferenceRow.create(key={"name": "stage8-one"}, values={"value": 1})
    with pytest.raises(ReferenceDataDeclarationError, match="unreviewed"):
        ReferenceTable(
            table_name="runtime_bundles",
            key_columns=("name",),
            managed_prefix_column="name",
            managed_prefix="stage8-",
            rows=(row,),
        )
    with pytest.raises(ReferenceDataDeclarationError, match="duplicate"):
        ReferenceTable(
            table_name="tax_benefit_models",
            key_columns=("name",),
            managed_prefix_column="name",
            managed_prefix="stage8-",
            rows=(row, row),
        )
    with pytest.raises(ReferenceDataDeclarationError, match="unsupported"):
        ReferenceRow.create(key={"name": "stage8-unsafe"}, values={"value": object()})


def test_operation_requires_reviewed_table_key_and_reversible_state() -> None:
    with pytest.raises(ReferenceDataMigrationError, match="unreviewed"):
        ReferenceRowChangeOp(
            "runtime_bundles",
            key={"name": "stage8-test"},
            before=None,
            after={"name": "stage8-test"},
        )
    with pytest.raises(ReferenceDataMigrationError, match="stable key"):
        ReferenceRowChangeOp(
            "tax_benefit_models",
            key={},
            before=None,
            after={"name": "stage8-test"},
        )

    operation = ReferenceRowChangeOp(
        "tax_benefit_models",
        key={"name": "stage8-test"},
        before={"name": "stage8-test", "description": "before"},
        after={"name": "stage8-test", "description": "after"},
    )
    assert operation.reverse().before == operation.after
    assert operation.reverse().after == operation.before


def test_renderer_is_deterministic_and_uses_the_registered_op_surface() -> None:
    operation = ReferenceRowChangeOp(
        "tax_benefit_models",
        key={"name": "stage8-test"},
        before=None,
        after={"name": "stage8-test", "description": "test"},
    )

    first = _render_reference_row_change(None, operation)
    second = _render_reference_row_change(None, operation)

    assert first == second
    assert first.startswith("op.v2_reference_row_change(")
    assert hasattr(Operations, "v2_reference_row_change")
    assert operation.to_diff_tuple() == (
        "v2_reference_row_change",
        "tax_benefit_models",
        {"name": "stage8-test"},
        None,
        {"description": "test", "name": "stage8-test"},
    )


def test_generated_operation_executes_and_downgrades_against_reflected_table() -> None:
    engine = sa.create_engine("sqlite://")
    declaration = REFERENCE_DATA[0]
    row = declaration.rows[0]
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
        table = V2_METADATA.tables[declaration.table_name].to_metadata(
            sa.MetaData(schema="public")
        )
        table.create(connection)
        operations = Operations(MigrationContext.configure(connection))
        insert = ReferenceRowChangeOp(
            declaration.table_name,
            key=dict(row.key),
            before=None,
            after=row.complete_values,
        )

        operations.invoke(insert)
        stored = connection.execute(sa.select(table)).mappings().one()
        assert stored["name"] == "stage8-platform-validation"

        update_values = {**row.complete_values, "description": "updated"}
        update = ReferenceRowChangeOp(
            declaration.table_name,
            key=dict(row.key),
            before=row.complete_values,
            after=update_values,
        )
        operations.invoke(update)
        assert connection.execute(sa.select(table.c.description)).scalar_one() == (
            "updated"
        )
        operations.invoke(update.reverse())
        operations.invoke(insert.reverse())
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(table)
            ).scalar_one()
            == 0
        )
    engine.dispose()


def test_generated_data_is_ordered_between_constructive_and_destructive_schema() -> (
    None
):
    metadata = sa.MetaData()
    table = sa.Table("example", metadata, sa.Column("id", sa.Integer, primary_key=True))
    create = ops.CreateTableOp.from_table(table)
    drop = ops.DropTableOp.from_table(table)
    data = ReferenceRowChangeOp(
        "tax_benefit_models",
        key={"name": "stage8-test"},
        before=None,
        after={"name": "stage8-test"},
    )
    script = SimpleNamespace(
        upgrade_ops=SimpleNamespace(ops=[drop, data, create]),
        downgrade_ops=SimpleNamespace(ops=[]),
    )

    order_generated_operations(None, None, [script])

    assert script.upgrade_ops.ops == [create, data, drop]
    assert isinstance(script.downgrade_ops.ops[0], ops.CreateTableOp)
    assert isinstance(script.downgrade_ops.ops[1], ReferenceRowChangeOp)
    assert isinstance(script.downgrade_ops.ops[2], ops.DropTableOp)


def test_comparator_deletes_children_first_and_upserts_parents_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import policyengine_api.data.v2.reference_data_autogenerate as module

    parent_remove = ReferenceRowChangeOp(
        "tax_benefit_models",
        key={"name": "stage8-parent"},
        before={"name": "stage8-parent"},
        after=None,
    )
    parent_insert = parent_remove.reverse()
    child_remove = ReferenceRowChangeOp(
        "tax_benefit_model_versions",
        key={"version": "stage8-child"},
        before={"version": "stage8-child"},
        after=None,
    )
    child_insert = child_remove.reverse()
    differences = iter(
        [([parent_remove], [parent_insert]), ([child_remove], [child_insert])]
    )
    monkeypatch.setattr(module, "_table_differences", lambda *_: next(differences))
    monkeypatch.setattr(
        module.sa,
        "inspect",
        lambda _: SimpleNamespace(
            get_table_names=lambda schema: list(EXPECTED_V2_TABLES)
        ),
    )
    upgrade = ops.UpgradeOps(ops=[])

    compare_reference_data(SimpleNamespace(connection=object()), upgrade, {None})

    assert upgrade.ops == [
        child_remove,
        parent_remove,
        parent_insert,
        child_insert,
    ]
