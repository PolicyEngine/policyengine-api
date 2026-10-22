"""Schema-only declarations of the v2 tables and columns a later revision drops.

The simulation service owns household jobs, simulations, reports, report runs
and their outputs in its own ``simulation`` schema. The Public API's copies of
those 15 tables, and the retired ``country`` and ``label`` columns of the
simulation and report associations, stay in the database until a later v2
revision drops them. That revision runs while this release serves traffic, so
this release must never read or write them.

They stay declared here only so the v2 metadata keeps matching the schema:
``alembic check`` and the migration environment's head-schema validation
compare the two. They are plain SQLAlchemy tables and columns that no model
maps, so no ORM query, insert, update, relationship or cascade reaches them.
Nothing imports this module except the models package, which registers it.
Deleting it is what makes autogeneration produce the revision that drops them.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlmodel import SQLModel

from policyengine_api.data.v2.models.associations import (
    UserReportAssociation,
    UserSimulationAssociation,
)

METADATA = SQLModel.metadata

# Each lifecycle enum has the same four values.
LIFECYCLE_STATES = ("pending", "running", "succeeded", "failed")
REPORT_RUN_TRIGGERS = ("initial", "manual", "system")
AGGREGATE_TYPES = ("sum", "mean", "count")
DECILE_TYPES = ("income", "wealth")

# The retired association columns, by table, with their string lengths.
RETIRED_ASSOCIATION_COLUMNS = {
    UserSimulationAssociation.__tablename__: {"country": 16, "label": 255},
    UserReportAssociation.__tablename__: {"country": 16, "label": 255},
}


def _enum(values: tuple[str, ...], name: str) -> Enum:
    return Enum(*values, name=name)


def _identified_columns() -> list[Column]:
    return [
        Column("id", Uuid(), primary_key=True),
        Column(
            "created_at",
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    ]


def _timestamped_columns() -> list[Column]:
    return [
        *_identified_columns(),
        Column(
            "updated_at",
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    ]


def _reference(
    name: str,
    target: str,
    ondelete: str,
    *,
    nullable: bool,
    index: bool = False,
) -> Column:
    return Column(
        name,
        Uuid(),
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=index,
    )


def _report_run_reference() -> Column:
    return _reference("report_run_id", "report_runs.id", "CASCADE", nullable=False)


def _simulation_reference(name: str) -> Column:
    return _reference(name, "simulations.id", "RESTRICT", nullable=False)


def _comparison_references() -> list[Column]:
    return [
        _report_run_reference(),
        _simulation_reference("baseline_simulation_id"),
        _simulation_reference("reform_simulation_id"),
    ]


def _geographic_impact_columns() -> list[Column]:
    return [
        *_identified_columns(),
        *_comparison_references(),
        Column("average_household_income_change", Float(), nullable=False),
        Column("relative_household_income_change", Float(), nullable=False),
        Column("population", Float(), nullable=False),
    ]


HOUSEHOLD_JOBS = Table(
    "household_jobs",
    METADATA,
    *_identified_columns(),
    Column("country", String(16), nullable=False),
    Column("request_data", JSON(), nullable=False),
    _reference("policy_id", "policies.id", "SET NULL", nullable=True),
    _reference("dynamic_id", "dynamics.id", "SET NULL", nullable=True),
    Column(
        "status",
        _enum(LIFECYCLE_STATES, "v2_household_job_status"),
        nullable=False,
    ),
    Column("error_message", String(), nullable=True),
    Column("result", JSON(), nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Index("ix_household_jobs_status_created_at", "status", "created_at"),
)

SIMULATIONS = Table(
    "simulations",
    METADATA,
    *_timestamped_columns(),
    Column(
        "simulation_type",
        _enum(("household", "economy"), "v2_simulation_type"),
        nullable=False,
    ),
    _reference("dataset_id", "datasets.id", "RESTRICT", nullable=True),
    _reference("household_id", "households.id", "RESTRICT", nullable=True),
    _reference("policy_id", "policies.id", "SET NULL", nullable=True),
    _reference("dynamic_id", "dynamics.id", "SET NULL", nullable=True),
    _reference(
        "tax_benefit_model_version_id",
        "tax_benefit_model_versions.id",
        "RESTRICT",
        nullable=False,
        index=True,
    ),
    _reference("output_dataset_id", "datasets.id", "SET NULL", nullable=True),
    _reference("region_id", "regions.id", "SET NULL", nullable=True),
    Column("status", _enum(LIFECYCLE_STATES, "v2_simulation_status"), nullable=False),
    Column("error_message", String(), nullable=True),
    Column("filter_field", String(128), nullable=True),
    Column("filter_value", String(255), nullable=True),
    Column("filter_strategy", String(64), nullable=True),
    Column("year", Integer(), nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("household_result", JSON(), nullable=True),
    CheckConstraint(
        "(simulation_type = 'household' AND household_id IS NOT NULL "
        "AND dataset_id IS NULL) OR "
        "(simulation_type = 'economy' AND dataset_id IS NOT NULL "
        "AND household_id IS NULL)",
        name="ck_simulations_type_input",
    ),
    CheckConstraint(
        "(filter_field IS NULL) = (filter_value IS NULL)",
        name="ck_simulations_filter_pair",
    ),
    CheckConstraint(
        "year IS NULL OR year BETWEEN 1900 AND 2200",
        name="ck_simulations_year",
    ),
    Index("ix_simulations_status_created_at", "status", "created_at"),
)

REPORTS = Table(
    "reports",
    METADATA,
    *_timestamped_columns(),
    Column("label", String(255), nullable=False),
    Column("description", String(), nullable=True),
    Column("country", String(16), nullable=False),
    Column("type", String(128), nullable=True),
    _reference("user_id", "users.id", "SET NULL", nullable=True),
    _reference(
        "tax_benefit_model_id",
        "tax_benefit_models.id",
        "RESTRICT",
        nullable=False,
        index=True,
    ),
    _reference("policy_id", "policies.id", "SET NULL", nullable=True),
    _reference("baseline_simulation_id", "simulations.id", "SET NULL", nullable=True),
    _reference("reform_simulation_id", "simulations.id", "SET NULL", nullable=True),
    _reference("household_id", "households.id", "RESTRICT", nullable=True),
    _reference("dataset_id", "datasets.id", "SET NULL", nullable=True),
    _reference("region_id", "regions.id", "SET NULL", nullable=True),
    Column("year", Integer(), nullable=True),
    Column("inputs", JSON(), nullable=False),
    CheckConstraint(
        "year IS NULL OR year BETWEEN 1900 AND 2200",
        name="ck_reports_year",
    ),
    Index("ix_reports_country_type_created_at", "country", "type", "created_at"),
)

REPORT_RUNS = Table(
    "report_runs",
    METADATA,
    *_timestamped_columns(),
    _reference("report_id", "reports.id", "CASCADE", nullable=False),
    Column("country_package_version", String(128), nullable=False),
    Column("policyengine_version", String(128), nullable=False),
    Column("status", _enum(LIFECYCLE_STATES, "v2_report_run_status"), nullable=False),
    Column(
        "trigger",
        _enum(REPORT_RUN_TRIGGERS, "v2_report_run_trigger"),
        nullable=False,
    ),
    Column("idempotency_key", Uuid(), nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("error_message", String(), nullable=True),
    Column("markdown", Text(), nullable=True),
    UniqueConstraint(
        "report_id",
        "idempotency_key",
        name="uq_report_runs_report_idempotency_key",
    ),
    CheckConstraint(
        "status NOT IN ('succeeded', 'failed') OR completed_at IS NOT NULL",
        name="ck_report_runs_terminal_completion",
    ),
    Index(
        "ix_report_runs_current_output",
        "report_id",
        "status",
        "country_package_version",
        "policyengine_version",
        "completed_at",
        "id",
    ),
)

AGGREGATES = Table(
    "aggregates",
    METADATA,
    *_identified_columns(),
    _report_run_reference(),
    _simulation_reference("simulation_id"),
    Column("variable", String(512), nullable=False),
    Column(
        "aggregate_type",
        _enum(AGGREGATE_TYPES, "v2_aggregate_type"),
        nullable=False,
    ),
    Column("entity", String(128), nullable=True),
    Column("filter_config", JSON(), nullable=False),
    Column("status", _enum(LIFECYCLE_STATES, "v2_output_status"), nullable=False),
    Column("error_message", String(), nullable=True),
    Column("result", Float(), nullable=True),
    Index("ix_aggregates_report_run_status", "report_run_id", "status"),
)

CHANGE_AGGREGATES = Table(
    "change_aggregates",
    METADATA,
    *_identified_columns(),
    *_comparison_references(),
    Column("variable", String(512), nullable=False),
    Column(
        "aggregate_type",
        _enum(AGGREGATE_TYPES, "v2_aggregate_type"),
        nullable=False,
    ),
    Column("entity", String(128), nullable=True),
    Column("filter_config", JSON(), nullable=False),
    Column("change_geq", Float(), nullable=True),
    Column("change_leq", Float(), nullable=True),
    Column("status", _enum(LIFECYCLE_STATES, "v2_output_status"), nullable=False),
    Column("error_message", String(), nullable=True),
    Column("result", Float(), nullable=True),
    Index("ix_change_aggregates_report_run_status", "report_run_id", "status"),
)

BUDGET_SUMMARY = Table(
    "budget_summary",
    METADATA,
    *_identified_columns(),
    *_comparison_references(),
    Column("variable_name", String(512), nullable=False),
    Column("entity", String(128), nullable=False),
    Column("baseline_total", Float(), nullable=True),
    Column("reform_total", Float(), nullable=True),
    Column("change", Float(), nullable=True),
    UniqueConstraint(
        "report_run_id",
        "variable_name",
        "entity",
        name="uq_budget_summary_run_variable_entity",
    ),
)

DECILE_IMPACTS = Table(
    "decile_impacts",
    METADATA,
    *_identified_columns(),
    *_comparison_references(),
    Column("income_variable", String(512), nullable=False),
    Column("entity", String(128), nullable=False),
    Column("decile", Integer(), nullable=False),
    Column("quantiles", Integer(), nullable=False),
    Column("baseline_mean", Float(), nullable=True),
    Column("reform_mean", Float(), nullable=True),
    Column("absolute_change", Float(), nullable=True),
    Column("relative_change", Float(), nullable=True),
    Column("count_better_off", Float(), nullable=True),
    Column("count_worse_off", Float(), nullable=True),
    Column("count_no_change", Float(), nullable=True),
    UniqueConstraint(
        "report_run_id",
        "income_variable",
        "entity",
        "decile",
        "quantiles",
        name="uq_decile_impacts_run_measure",
    ),
    CheckConstraint("quantiles > 0", name="ck_decile_impacts_quantiles"),
    CheckConstraint("decile BETWEEN 1 AND quantiles", name="ck_decile_impacts_decile"),
)

INTRA_DECILE_IMPACTS = Table(
    "intra_decile_impacts",
    METADATA,
    *_identified_columns(),
    *_comparison_references(),
    Column("decile_type", _enum(DECILE_TYPES, "v2_decile_type"), nullable=False),
    Column("decile", Integer(), nullable=False),
    Column("lose_more_than_5pct", Float(), nullable=True),
    Column("lose_less_than_5pct", Float(), nullable=True),
    Column("no_change", Float(), nullable=True),
    Column("gain_less_than_5pct", Float(), nullable=True),
    Column("gain_more_than_5pct", Float(), nullable=True),
    UniqueConstraint(
        "report_run_id",
        "decile_type",
        "decile",
        name="uq_intra_decile_impacts_run_type_decile",
    ),
    CheckConstraint(
        "decile BETWEEN 0 AND 10",
        name="ck_intra_decile_impacts_decile",
    ),
)

INEQUALITY = Table(
    "inequality",
    METADATA,
    *_identified_columns(),
    _report_run_reference(),
    _simulation_reference("simulation_id"),
    Column("income_variable", String(512), nullable=False),
    Column("entity", String(128), nullable=False),
    Column("gini", Float(), nullable=True),
    Column("top_10_share", Float(), nullable=True),
    Column("top_1_share", Float(), nullable=True),
    Column("bottom_50_share", Float(), nullable=True),
    UniqueConstraint(
        "report_run_id",
        "simulation_id",
        "income_variable",
        "entity",
        name="uq_inequality_run_simulation_measure",
    ),
)

POVERTY = Table(
    "poverty",
    METADATA,
    *_identified_columns(),
    _report_run_reference(),
    _simulation_reference("simulation_id"),
    Column("poverty_type", String(128), nullable=False),
    Column("entity", String(128), nullable=False),
    Column("filter_variable", String(512), nullable=True),
    Column("headcount", Float(), nullable=True),
    Column("total_population", Float(), nullable=True),
    Column("rate", Float(), nullable=True),
    Index(
        "ix_poverty_run_simulation_type",
        "report_run_id",
        "simulation_id",
        "poverty_type",
    ),
)

PROGRAM_STATISTICS = Table(
    "program_statistics",
    METADATA,
    *_identified_columns(),
    *_comparison_references(),
    Column("program_name", String(512), nullable=False),
    Column("entity", String(128), nullable=False),
    Column("is_tax", Boolean(), nullable=False),
    Column("baseline_total", Float(), nullable=True),
    Column("reform_total", Float(), nullable=True),
    Column("change", Float(), nullable=True),
    Column("baseline_count", Float(), nullable=True),
    Column("reform_count", Float(), nullable=True),
    Column("winners", Float(), nullable=True),
    Column("losers", Float(), nullable=True),
    UniqueConstraint(
        "report_run_id",
        "program_name",
        "entity",
        name="uq_program_statistics_run_program_entity",
    ),
)

CONGRESSIONAL_DISTRICT_IMPACTS = Table(
    "congressional_district_impacts",
    METADATA,
    *_geographic_impact_columns(),
    Column("district_geoid", Integer(), nullable=False),
    Column("state_fips", Integer(), nullable=False),
    Column("district_number", Integer(), nullable=False),
    UniqueConstraint(
        "report_run_id",
        "district_geoid",
        name="uq_congressional_district_impacts_run_geoid",
    ),
)

CONSTITUENCY_IMPACTS = Table(
    "constituency_impacts",
    METADATA,
    *_geographic_impact_columns(),
    Column("constituency_code", String(64), nullable=False),
    Column("constituency_name", String(255), nullable=False),
    Column("x", Integer(), nullable=False),
    Column("y", Integer(), nullable=False),
    UniqueConstraint(
        "report_run_id",
        "constituency_code",
        name="uq_constituency_impacts_run_code",
    ),
)

LOCAL_AUTHORITY_IMPACTS = Table(
    "local_authority_impacts",
    METADATA,
    *_geographic_impact_columns(),
    Column("local_authority_code", String(64), nullable=False),
    Column("local_authority_name", String(255), nullable=False),
    Column("x", Integer(), nullable=False),
    Column("y", Integer(), nullable=False),
    UniqueConstraint(
        "report_run_id",
        "local_authority_code",
        name="uq_local_authority_impacts_run_code",
    ),
)

RETIRED_TABLES = (
    HOUSEHOLD_JOBS,
    SIMULATIONS,
    REPORTS,
    REPORT_RUNS,
    AGGREGATES,
    CHANGE_AGGREGATES,
    BUDGET_SUMMARY,
    DECILE_IMPACTS,
    INTRA_DECILE_IMPACTS,
    INEQUALITY,
    POVERTY,
    PROGRAM_STATISTICS,
    CONGRESSIONAL_DISTRICT_IMPACTS,
    CONSTITUENCY_IMPACTS,
    LOCAL_AUTHORITY_IMPACTS,
)


def _declare_retired_association_columns() -> None:
    """Add the retired columns to the association tables, but not their models.

    The association models no longer declare these columns, so their mappers
    never select, insert or update them: a column appended to a table after
    its mapper exists stays unmapped.
    """
    for table_name, columns in RETIRED_ASSOCIATION_COLUMNS.items():
        for column_name, length in columns.items():
            METADATA.tables[table_name].append_column(
                Column(column_name, String(length), nullable=True)
            )


_declare_retired_association_columns()
