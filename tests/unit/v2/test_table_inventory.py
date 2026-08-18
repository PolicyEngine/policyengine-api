"""Tests for the reviewed Stage 8 table allowlist."""

import pytest

from policyengine_api.data.v2.table_inventory import (
    EXPECTED_V2_TABLES,
    PROHIBITED_V2_TABLES,
    V1_ONLY_TABLES,
    V2_TABLE_GROUPS,
    V2TableInventoryError,
    validate_v2_table_inventory,
)


def test_reviewed_table_groups_are_disjoint_and_complete() -> None:
    grouped_tables = [
        table_name for _, table_names in V2_TABLE_GROUPS for table_name in table_names
    ]

    assert len(grouped_tables) == len(set(grouped_tables))
    assert frozenset(grouped_tables) == EXPECTED_V2_TABLES
    assert "reports" in EXPECTED_V2_TABLES
    assert "report_runs" in EXPECTED_V2_TABLES
    assert EXPECTED_V2_TABLES.isdisjoint(PROHIBITED_V2_TABLES)
    assert EXPECTED_V2_TABLES.isdisjoint(V1_ONLY_TABLES)


def test_exact_reviewed_inventory_is_accepted() -> None:
    validate_v2_table_inventory(EXPECTED_V2_TABLES)


@pytest.mark.parametrize(
    "table_name",
    ["runtime_bundles", "populations", "household", "unreviewed_predecessor"],
)
def test_unreviewed_tables_are_rejected(table_name: str) -> None:
    with pytest.raises(V2TableInventoryError, match=table_name):
        validate_v2_table_inventory(EXPECTED_V2_TABLES | {table_name})


def test_missing_reviewed_table_is_rejected() -> None:
    with pytest.raises(V2TableInventoryError, match="report_runs"):
        validate_v2_table_inventory(EXPECTED_V2_TABLES - {"report_runs"})
