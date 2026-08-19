"""Tests for targeted v2 metadata rejection rules."""

import pytest

from policyengine_api.data.v2.metadata_validation import (
    PROHIBITED_V2_TABLES,
    V1_ONLY_TABLES,
    V2MetadataValidationError,
    validate_v2_metadata_table_names,
)
from policyengine_api.data.v2.models import V2_METADATA


def test_current_metadata_contains_no_rejected_tables() -> None:
    validate_v2_metadata_table_names(V2_METADATA.tables)


@pytest.mark.parametrize(
    "table_name",
    ["runtime_bundles", "populations", "household", "user_profiles"],
)
def test_known_rejected_tables_are_identified(table_name: str) -> None:
    with pytest.raises(V2MetadataValidationError, match=table_name):
        validate_v2_metadata_table_names({*V2_METADATA.tables, table_name})


def test_rejection_sets_do_not_block_current_metadata() -> None:
    table_names = set(V2_METADATA.tables)

    assert table_names.isdisjoint(PROHIBITED_V2_TABLES)
    assert table_names.isdisjoint(V1_ONLY_TABLES)


def test_new_table_name_requires_no_allowlist_update() -> None:
    validate_v2_metadata_table_names({*V2_METADATA.tables, "future_domain_table"})
