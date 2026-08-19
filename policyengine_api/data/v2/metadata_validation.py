"""Targeted validation for tables that must not enter v2 metadata."""

from collections.abc import Iterable


# These names belong only to the existing v1 database domain. Names that are
# intentionally shared between v1 and v2, such as `simulations` and
# `user_policies`, are excluded from this targeted rejection set.
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

# The v2 design explicitly rejects the former runtime-bundle indirection and a
# standalone population model. Population-valued columns on impact tables are
# unrelated to these table names.
PROHIBITED_V2_TABLES = frozenset(
    {
        "population",
        "populations",
        "runtime_bundle",
        "runtime_bundles",
    }
)


class V2MetadataValidationError(RuntimeError):
    """Raised when v2 metadata contains a specifically rejected table."""


def validate_v2_metadata_table_names(table_names: Iterable[str]) -> None:
    """Reject known v1-only and explicitly prohibited v2 table names."""

    actual = frozenset(table_names)
    prohibited = sorted(actual & PROHIBITED_V2_TABLES)
    v1_only = sorted(actual & V1_ONLY_TABLES)
    if prohibited or v1_only:
        raise V2MetadataValidationError(
            "API v2-alpha metadata contains rejected tables: "
            f"prohibited={prohibited}, v1_only={v1_only}"
        )
