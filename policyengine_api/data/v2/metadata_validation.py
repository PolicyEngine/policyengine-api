"""Targeted validation for tables that must not enter v2 metadata."""

from collections.abc import Iterable

# These names belong only to the existing v1 database domain. Names that v1
# and v2 both use, such as `user_policies`, are excluded from this targeted
# rejection set.
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


# The simulation-domain tables a v2 revision dropped. The simulation service
# has its own replacements for all of them in its ``simulation`` schema except
# ``aggregates`` and ``change_aggregates``, v2 alpha's custom totals, which
# were unused and have none. The Public API's metadata must not declare them
# again.
SIMULATION_DOMAIN_TABLES = frozenset(
    {
        "aggregates",
        "budget_summary",
        "change_aggregates",
        "congressional_district_impacts",
        "constituency_impacts",
        "decile_impacts",
        "household_jobs",
        "inequality",
        "intra_decile_impacts",
        "local_authority_impacts",
        "poverty",
        "program_statistics",
        "report_runs",
        "reports",
        "simulations",
    }
)


class V2MetadataValidationError(RuntimeError):
    """Raised when v2 metadata contains a specifically rejected table."""


def validate_v2_metadata_table_names(table_names: Iterable[str]) -> None:
    """Reject known v1-only, dropped simulation-domain and prohibited v2 tables."""
    actual = frozenset(table_names)
    prohibited = sorted(actual & PROHIBITED_V2_TABLES)
    v1_only = sorted(actual & V1_ONLY_TABLES)
    simulation_domain = sorted(actual & SIMULATION_DOMAIN_TABLES)
    if prohibited or v1_only or simulation_domain:
        msg = (
            "API v2-alpha metadata contains rejected tables: "
            f"prohibited={prohibited}, v1_only={v1_only}, "
            f"simulation_domain={simulation_domain}"
        )
        raise V2MetadataValidationError(msg)
