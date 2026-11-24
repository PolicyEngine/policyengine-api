"""Tests for targeted v2 metadata rejection rules."""

import pytest

from policyengine_api.data.v2.metadata_validation import (
    PROHIBITED_V2_TABLES,
    V1_ONLY_TABLES,
    V2MetadataValidationError,
    validate_v2_metadata_table_names,
)
from policyengine_api.data.v2.models import TaxBenefitModel

# The registry every v2 model is mapped on, SQLModel's own.
V2_REGISTRY = TaxBenefitModel._sa_registry


def _v2_table_names() -> set[str]:
    """Return the name of every table a v2 model maps."""
    return {mapper.class_.__tablename__ for mapper in V2_REGISTRY.mappers}


def test_current_metadata_contains_no_rejected_tables() -> None:
    validate_v2_metadata_table_names(_v2_table_names())


@pytest.mark.parametrize(
    "table_name",
    ["runtime_bundles", "populations", "household", "user_profiles"],
)
def test_known_rejected_tables_are_identified(table_name: str) -> None:
    with pytest.raises(V2MetadataValidationError, match=table_name):
        validate_v2_metadata_table_names({*_v2_table_names(), table_name})


def test_rejection_sets_do_not_block_current_metadata() -> None:
    table_names = _v2_table_names()

    assert table_names.isdisjoint(PROHIBITED_V2_TABLES)
    assert table_names.isdisjoint(V1_ONLY_TABLES)


def test_new_table_name_requires_no_allowlist_update() -> None:
    validate_v2_metadata_table_names({*_v2_table_names(), "future_domain_table"})


@pytest.mark.parametrize("table_name", ["simulations", "simulation_runs"])
def test_names_shared_with_v1_are_accepted(table_name: str) -> None:
    """v2 reuses these v1 table names for its own tables, in its own database."""
    assert table_name in _v2_table_names()
    assert table_name not in V1_ONLY_TABLES
    validate_v2_metadata_table_names({*_v2_table_names(), table_name})
