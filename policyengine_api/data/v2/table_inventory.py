"""Reviewed Stage 8 API v2-alpha application-table inventory.

This module is deliberately independent of ORM imports. SQLModel metadata,
Alembic generation, lifecycle tests, and live-schema comparisons all use this
single allowlist. Supabase-managed tables and Alembic's version table are not
application tables and are outside this inventory.
"""

from collections.abc import Iterable


V2_TABLE_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "identity",
        frozenset(
            {
                "users",
                "user_household_associations",
                "user_policies",
                "user_report_associations",
                "user_simulation_associations",
            }
        ),
    ),
    (
        "model_metadata",
        frozenset(
            {
                "tax_benefit_models",
                "tax_benefit_model_versions",
            }
        ),
    ),
    (
        "regions_and_datasets",
        frozenset(
            {
                "regions",
                "datasets",
                "dataset_versions",
                "region_datasets",
            }
        ),
    ),
    (
        "variables_and_parameters",
        frozenset(
            {
                "variables",
                "parameter_nodes",
                "parameters",
                "parameter_values",
            }
        ),
    ),
    (
        "policies",
        frozenset(
            {
                "policies",
                "dynamics",
            }
        ),
    ),
    (
        "households_and_simulations",
        frozenset(
            {
                "households",
                "household_jobs",
                "simulations",
            }
        ),
    ),
    (
        "reports_and_outputs",
        frozenset(
            {
                "reports",
                "report_runs",
                "aggregates",
                "change_aggregates",
            }
        ),
    ),
    (
        "impact_results",
        frozenset(
            {
                "budget_summary",
                "congressional_district_impacts",
                "constituency_impacts",
                "decile_impacts",
                "inequality",
                "intra_decile_impacts",
                "local_authority_impacts",
                "poverty",
                "program_statistics",
            }
        ),
    ),
)

EXPECTED_V2_TABLES = frozenset(
    table_name for _, table_names in V2_TABLE_GROUPS for table_name in table_names
)

# These v1-only names make accidental V1Base metadata registration especially
# clear. Names intentionally reviewed for both domains, such as `simulations`
# and `user_policies`, remain valid because the exact allowlist is authoritative.
V1_ONLY_TABLES = frozenset(
    {
        "analysis",
        "computed_household",
        "economy",
        "household",
        "legacy_report_output_aliases",
        "policy",
        "reform_impact",
        "report_output_runs",
        "report_outputs",
        "simulation_runs",
        "tracers",
        "user_profiles",
    }
)

# Stage 8 explicitly rejects the former runtime-bundle indirection and any
# standalone population model. Population-valued columns on reviewed impact
# tables are unrelated to these prohibited table names.
PROHIBITED_V2_TABLES = frozenset(
    {
        "population",
        "populations",
        "runtime_bundle",
        "runtime_bundles",
    }
)


class V2TableInventoryError(RuntimeError):
    """Raised when table metadata differs from the reviewed Stage 8 schema."""


def validate_v2_table_inventory(table_names: Iterable[str]) -> None:
    """Fail closed unless *table_names* exactly match the reviewed allowlist."""

    actual = frozenset(table_names)
    if actual == EXPECTED_V2_TABLES:
        return

    missing = sorted(EXPECTED_V2_TABLES - actual)
    unexpected = sorted(actual - EXPECTED_V2_TABLES)
    prohibited = sorted(actual & PROHIBITED_V2_TABLES)
    v1_only = sorted(actual & V1_ONLY_TABLES)
    raise V2TableInventoryError(
        "API v2-alpha table inventory mismatch: "
        f"missing={missing}, unexpected={unexpected}, "
        f"prohibited={prohibited}, v1_only={v1_only}"
    )
