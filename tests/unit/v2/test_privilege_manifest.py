"""The v2 privilege manifest covers every table and every connector's needs.

Rule ``api.v2.runtime-privileges-declared`` (rules/registry.toml).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa

from policyengine_api.data.v2 import models
from policyengine_api.data.v2.catalog.publication_statistics import (
    CATALOG_STATISTICS_TABLES,
)
from policyengine_api.data.v2.models import V2_REGISTRY, V2_TABLE_NAMES
from policyengine_api.data.v2.privilege_requirements import (
    required_privileges,
    undeclared_requirements,
)
from policyengine_api.data.v2.privileges import (
    CATALOG_WRITER_ROLE,
    MODAL_WORKER_ROLE,
    NO_ACCESS,
    READ,
    READ_INSERT,
    READ_INSERT_DELETE,
    READ_INSERT_UPDATE,
    READ_WRITE,
    ROLES_AWAITING_PROVISIONING,
    RUNTIME_ROLE,
    SIMULATION_SERVICE_ROLE,
    TABLE_ACCESS,
    ColumnPrivilege,
    InvalidDeploymentEnvironmentError,
    TablePrivilege,
    declared_privileges,
    stage12_role,
    update_columns,
)
from tests.unit.v2.v2_schema_reading import stored_v2_schema

PROJECT_ROOT = Path(__file__).parents[3]
SERVICES_ROOT = PROJECT_ROOT / "policyengine_api" / "services" / "v2"
PROOF_FIXTURES = PROJECT_ROOT / "rules/fixtures/api.v2.runtime-privileges-declared"
STAGE12_PACKAGES = frozenset({"comparison_runs"})
TEST_ENVIRONMENT = "staging"
# The rows the simulation service creates, and the run tables among them. A
# simulation run's cliff calculation is started and finished like a run.
SIMULATION_SERVICE_CREATES = frozenset(
    {
        "simulations",
        "reports",
        "simulation_runs",
        "report_runs",
        "budget_window_runs",
        "household_jobs",
        "cliff_impacts",
    }
)
RUN_STATUS_TABLES = frozenset(
    {"simulation_runs", "report_runs", "household_jobs", "cliff_impacts"}
)
# The run columns the Modal workers update: a run's state and its results.
WORKER_RUN_STATE_COLUMNS = frozenset(
    {
        "status",
        "modal_call_id",
        "error_message",
        "started_at",
        "completed_at",
        "updated_at",
    }
)
WORKER_RESULT_COLUMNS = {
    "simulation_runs": frozenset({"output_uri", "output_sha256", "household_result"}),
    "report_runs": frozenset(
        {
            "spm_provenance",
            "data_version",
        }
    ),
    "household_jobs": frozenset({"result"}),
    "cliff_impacts": frozenset({"cliff_gap", "cliff_share"}),
}
# The run columns the simulation service updates: it records a Modal call's ID
# when Modal accepts the call, and fails the run when Modal refuses it.
SERVICE_RUN_STATE_COLUMNS = frozenset(
    {"status", "modal_call_id", "error_message", "completed_at", "updated_at"}
)
# A budget-window run has no Modal call of its own. Each year's Modal
# coordinator starts the window's next unstarted year when its year finishes;
# the last year to finish marks the window succeeded, and a failed year fails
# it.
WORKER_WINDOW_RUN_COLUMNS = frozenset(
    {"status", "error_message", "started_at", "completed_at", "updated_at"}
)
# The simulation service starts a window's first years at submit, and fails
# the window at once when Modal refuses their calls.
SERVICE_WINDOW_RUN_COLUMNS = frozenset(
    {"status", "error_message", "completed_at", "updated_at"}
)
# What a run is: no role may change these after the simulation service writes
# them.
RUN_DEFINITION_COLUMNS = {
    "simulation_runs": frozenset(
        {
            "simulation_id",
            "year",
            "tax_benefit_model_version_id",
            "country_package_version",
            "policyengine_version",
            "dataset_id",
            "region_id",
            "forced",
        }
    ),
    "report_runs": frozenset(
        {
            "report_id",
            "baseline_simulation_run_id",
            "reform_simulation_run_id",
            "budget_window_run_id",
            "year",
            "country_package_version",
            "policyengine_version",
            "idempotency_key",
            "forced",
        }
    ),
    "household_jobs": frozenset(
        {
            "country",
            "household_id",
            "year",
            "policy_id",
            "dynamic_id",
            "request_data",
            "tax_benefit_model_version_id",
            "country_package_version",
            "policyengine_version",
        }
    ),
    "budget_window_runs": frozenset(
        {
            "report_id",
            "tax_benefit_model_version_id",
            "policyengine_version",
            "recalculate",
        }
    ),
    # A cliff calculation always calculates the run it was inserted for.
    "cliff_impacts": frozenset({"simulation_run_id"}),
}
# The policy, dynamic, household and catalog rows a run needs.
RUN_INPUT_TABLES = frozenset(
    {
        "policies",
        "dynamics",
        "households",
        "tax_benefit_models",
        "tax_benefit_model_versions",
        "regions",
        "datasets",
        "parameters",
        "parameter_values",
        "dynamic_parameters",
        "dynamic_parameter_values",
    }
)
RESULT_TABLES = frozenset(
    {
        "labor_supply_responses",
        "labor_supply_decile_responses",
        "budget_summary",
        "congressional_district_impacts",
        "constituency_impacts",
        "decile_impacts",
        "inequality",
        "intra_decile_impacts",
        "local_authority_impacts",
        "poverty",
        "program_statistics",
        "withheld_area_codes",
    }
)
WRITE_PRIVILEGES = frozenset(
    {TablePrivilege.INSERT, TablePrivilege.UPDATE, TablePrivilege.DELETE}
)


def _table_by_model() -> dict[str, str]:
    return {
        name: model.__tablename__
        for name in dir(models)
        if isinstance(model := getattr(models, name), type)
        and isinstance(getattr(model, "__tablename__", None), str)
    }


def _connector_modules(*, stage12: bool) -> list[str]:
    paths = sorted(
        path.relative_to(SERVICES_ROOT).as_posix()
        for path in SERVICES_ROOT.glob("*/database_connectors/*.py")
        if path.name != "__init__.py"
        and (path.parts[-3] in STAGE12_PACKAGES) is stage12
    )
    assert paths, "no connector modules found"
    return paths


def _missing(relative_path: str, role: str) -> list[str]:
    requirements = required_privileges(
        SERVICES_ROOT / relative_path, _table_by_model(), connector=relative_path
    )
    declared = declared_privileges(TEST_ENVIRONMENT)[role]
    return [
        f"{missing.connector}: {missing.privilege} on {missing.table_name} "
        f"({missing.reason})"
        for missing in undeclared_requirements(requirements, declared)
    ]


def _column_keys_by_table() -> dict[str, set[str]]:
    """Return the names of each v2 table's columns, as SQLite's copy stores them.

    A grant is on the table's columns, which include any a mapper leaves out.
    """
    return {name: set(table.columns) for name, table in stored_v2_schema().items()}


def test_every_v2_table_has_an_entry_for_every_managed_role() -> None:
    assert set(TABLE_ACCESS) == V2_TABLE_NAMES | {"alembic_version"}
    for role, privileges_by_table in declared_privileges(TEST_ENVIRONMENT).items():
        assert set(privileges_by_table) == set(TABLE_ACCESS), role


def test_v2_schema_has_no_sequences_the_manifest_would_need_to_cover() -> None:
    sequence_columns = [
        f"{mapper.class_.__tablename__}.{column.name}"
        for mapper in V2_REGISTRY.mappers
        for column in mapper.columns
        if isinstance(column.default, sa.Sequence)
        or column.identity is not None
        or (
            column.primary_key
            and len(mapper.primary_key) == 1
            and isinstance(column.type, sa.Integer)
            and column.autoincrement is not False
        )
    ]

    assert sequence_columns == [], (
        "a v2 column now uses a sequence; declare its privileges in "
        "policyengine_api/data/v2/privileges.py and extend the reconcile script"
    )


@pytest.mark.parametrize("relative_path", _connector_modules(stage12=False))
def test_runtime_connectors_need_only_declared_runtime_privileges(
    relative_path: str,
) -> None:
    assert _missing(relative_path, RUNTIME_ROLE) == []


@pytest.mark.parametrize("relative_path", _connector_modules(stage12=True))
def test_stage12_connectors_need_only_declared_stage12_privileges(
    relative_path: str,
) -> None:
    assert _missing(relative_path, stage12_role(TEST_ENVIRONMENT)) == []


def test_stage12_role_name_follows_the_deployment_environment() -> None:
    assert stage12_role("staging") == "policyengine_stage12_staging"
    assert stage12_role("production") == "policyengine_stage12_production"
    for invalid in ("", "Production", "prod-1", "x" * 40, "staging; DROP"):
        with pytest.raises(InvalidDeploymentEnvironmentError):
            stage12_role(invalid)


def test_declared_privileges_name_the_five_managed_roles() -> None:
    assert set(declared_privileges("production")) == {
        RUNTIME_ROLE,
        CATALOG_WRITER_ROLE,
        "policyengine_stage12_production",
        "policyengine_v2_simulation_service",
        "policyengine_v2_modal_worker",
    }


def test_the_simulation_roles_no_longer_await_provisioning() -> None:
    """Only declared roles await provisioning, and not the simulation roles.

    The simulation service and Modal worker roles exist in staging and
    production since 2026-11-09, so a deploy that can't find either one fails,
    as for every other declared role.
    """
    declared_roles = set(declared_privileges(TEST_ENVIRONMENT))

    assert declared_roles >= ROLES_AWAITING_PROVISIONING
    assert SIMULATION_SERVICE_ROLE not in ROLES_AWAITING_PROVISIONING
    assert MODAL_WORKER_ROLE not in ROLES_AWAITING_PROVISIONING


def test_simulation_service_creates_simulation_rows_and_reads_run_inputs() -> None:
    declared = declared_privileges(TEST_ENVIRONMENT)[SIMULATION_SERVICE_ROLE]

    expected = dict.fromkeys(TABLE_ACCESS, NO_ACCESS)
    expected |= dict.fromkeys(SIMULATION_SERVICE_CREATES, READ_INSERT)
    expected |= dict.fromkeys(RUN_INPUT_TABLES, READ)
    for table in RUN_STATUS_TABLES:
        expected[table] = READ_INSERT | {update_columns(*SERVICE_RUN_STATE_COLUMNS)}
    expected["budget_window_runs"] = READ_INSERT | {
        update_columns(*SERVICE_WINDOW_RUN_COLUMNS)
    }
    assert declared == expected


def test_modal_workers_write_only_run_status_and_results() -> None:
    declared = declared_privileges(TEST_ENVIRONMENT)[MODAL_WORKER_ROLE]

    expected = dict.fromkeys(TABLE_ACCESS, NO_ACCESS)
    expected |= dict.fromkeys(SIMULATION_SERVICE_CREATES, READ)
    expected |= dict.fromkeys(RESULT_TABLES, READ_INSERT)
    expected |= dict.fromkeys(RUN_INPUT_TABLES, READ)
    for table in RUN_STATUS_TABLES:
        worker_columns = WORKER_RUN_STATE_COLUMNS | WORKER_RESULT_COLUMNS[table]
        expected[table] = READ | {update_columns(*worker_columns)}
    expected["budget_window_runs"] = READ | {update_columns(*WORKER_WINDOW_RUN_COLUMNS)}
    assert declared == expected


def test_column_privileges_name_their_tables_columns_alone() -> None:
    """A whole-table privilege would override the same privilege's column list."""
    column_keys_by_table = _column_keys_by_table()
    for role, privileges_by_table in declared_privileges(TEST_ENVIRONMENT).items():
        for table, privileges in privileges_by_table.items():
            column_privileges = [
                privilege
                for privilege in privileges
                if isinstance(privilege, ColumnPrivilege)
            ]
            kinds = [privilege.privilege for privilege in column_privileges]
            assert len(kinds) == len(set(kinds)), (role, table)
            for privilege in column_privileges:
                assert privilege.columns, (role, table)
                assert privilege.columns <= column_keys_by_table[table], (
                    role,
                    table,
                )
                assert privilege.privilege not in privileges, (role, table)


def test_no_role_can_change_what_a_run_is() -> None:
    for role, privileges_by_table in declared_privileges(TEST_ENVIRONMENT).items():
        for table, definition_columns in RUN_DEFINITION_COLUMNS.items():
            privileges = privileges_by_table[table]
            assert TablePrivilege.UPDATE not in privileges, (role, table)
            for privilege in privileges:
                if isinstance(privilege, ColumnPrivilege):
                    assert privilege.columns.isdisjoint(definition_columns), (
                        role,
                        table,
                    )


def test_public_api_reads_simulations_runs_and_results_without_writing_them() -> None:
    declared = declared_privileges(TEST_ENVIRONMENT)[RUNTIME_ROLE]

    for table in SIMULATION_SERVICE_CREATES | RESULT_TABLES:
        assert declared[table] == READ, table
    for table in ("aggregates", "change_aggregates"):
        assert declared[table] == NO_ACCESS, table


def test_no_new_role_writes_the_public_api_tables() -> None:
    simulation_tables = SIMULATION_SERVICE_CREATES | RESULT_TABLES
    for role in (SIMULATION_SERVICE_ROLE, MODAL_WORKER_ROLE):
        writes = {
            table
            for table, privileges in declared_privileges(TEST_ENVIRONMENT)[role].items()
            if privileges & WRITE_PRIVILEGES
            or any(isinstance(privilege, ColumnPrivilege) for privilege in privileges)
        }
        assert writes <= simulation_tables, role


def test_rule_proof_runtime_privileges_declared() -> None:
    """Proof for rule api.v2.runtime-privileges-declared (rules/registry.toml).

    The bad fixture repeats the mistake behind issue #3977: a runtime connector
    reads ``legacy_policy_mappings``, which the runtime role had no grant on.
    """
    runtime_before_3977 = dict.fromkeys(TABLE_ACCESS, NO_ACCESS) | {
        "user_policies": READ_WRITE
    }
    table_by_model = _table_by_model()

    bad = required_privileges(PROOF_FIXTURES / "reads_bad.py", table_by_model)
    good = required_privileges(PROOF_FIXTURES / "reads_good.py", table_by_model)

    assert [
        (missing.table_name, missing.privilege)
        for missing in undeclared_requirements(bad, runtime_before_3977)
    ] == [("legacy_policy_mappings", TablePrivilege.SELECT)]
    assert undeclared_requirements(good, runtime_before_3977) == []


def test_the_catalog_writer_may_analyze_the_tables_publication_refreshes() -> None:
    """Publication runs ANALYZE on these tables, which needs MAINTAIN or ownership.

    The migration role owns every table, so the catalog writer needs MAINTAIN
    (PostgreSQL 17); without it, ANALYZE skips the table with only a warning.
    """
    writer_tables = declared_privileges(TEST_ENVIRONMENT)[CATALOG_WRITER_ROLE]

    assert {
        table
        for table, privileges in writer_tables.items()
        if TablePrivilege.MAINTAIN in privileges
    } == set(CATALOG_STATISTICS_TABLES)
    assert {"dynamic_parameters", "dynamic_parameter_values"} <= set(
        CATALOG_STATISTICS_TABLES
    )


def test_the_catalog_writer_deletes_only_the_rows_catalog_pruning_removes() -> None:
    """Catalog pruning deletes from four tables and marks the pruned version.

    It removes an older version's current-law values of policy and dynamic
    parameters, its parameter tree rows and its parameter search file, and
    records the pruning on the version's row, so the catalog writer holds
    DELETE on those four tables only and UPDATE on the model versions. It never
    deletes parameters, model versions or anything a policy or dynamic owns.
    """
    catalog_writer = declared_privileges(TEST_ENVIRONMENT)[CATALOG_WRITER_ROLE]

    assert {
        table
        for table, privileges in catalog_writer.items()
        if TablePrivilege.DELETE in privileges
    } == {
        "parameter_values",
        "dynamic_parameter_values",
        "parameter_tree_children",
        "parameter_search_files",
    }
    assert TablePrivilege.UPDATE in catalog_writer["tax_benefit_model_versions"]
    # MAINTAIN is for ANALYZE after publication, not for deleting.
    assert catalog_writer["parameter_tree_children"] == frozenset(
        {
            TablePrivilege.SELECT,
            TablePrivilege.INSERT,
            TablePrivilege.DELETE,
            TablePrivilege.MAINTAIN,
        }
    )
    assert catalog_writer["parameter_search_files"] == frozenset(
        {TablePrivilege.SELECT, TablePrivilege.INSERT, TablePrivilege.DELETE}
    )
    assert catalog_writer["parameter_values"] == READ_WRITE | {TablePrivilege.MAINTAIN}
    # Nothing in publication updates a value, so the new table has no UPDATE.
    assert catalog_writer["dynamic_parameter_values"] == frozenset(
        {
            TablePrivilege.SELECT,
            TablePrivilege.INSERT,
            TablePrivilege.DELETE,
            TablePrivilege.MAINTAIN,
        }
    )


def test_the_public_api_records_user_type_changes_but_never_rewrites_them() -> None:
    declared = declared_privileges(TEST_ENVIRONMENT)

    # It updates only when the user dismissed the change's notice.
    assert declared[RUNTIME_ROLE]["user_type_changes"] == READ_INSERT | {
        update_columns("dismissed_at")
    }
    for role, tables in declared.items():
        if role != RUNTIME_ROLE:
            assert tables["user_type_changes"] == NO_ACCESS, role


def test_the_public_api_revokes_and_accepts_invitations_but_never_deletes_them() -> (
    None
):
    declared = declared_privileges(TEST_ENVIRONMENT)

    assert declared[RUNTIME_ROLE]["user_invitations"] == READ_INSERT_UPDATE
    for role, tables in declared.items():
        if role != RUNTIME_ROLE:
            assert tables["user_invitations"] == NO_ACCESS, role


def test_the_public_api_records_each_users_report_run_requests() -> None:
    """API v1 writes a user's record of each report run they asked for.

    It reads, adds and deletes them, but never changes one: a later request
    for the same run is the same record. No other role reads them.
    """
    declared = declared_privileges(TEST_ENVIRONMENT)

    assert declared[RUNTIME_ROLE]["user_report_run_associations"] == (
        READ_INSERT_DELETE
    )
    for role, tables in declared.items():
        if role != RUNTIME_ROLE:
            assert tables["user_report_run_associations"] == NO_ACCESS, role


def test_cliff_calculations_are_started_by_the_service_and_finished_by_workers() -> (
    None
):
    """The simulation service inserts a run's cliff calculation and records its call.

    The Modal worker claims it, writes the cliff gap and share or the failure,
    and never inserts one; API v1 reads the results. The catalog
    writer and the Stage 12 role can do neither.
    """
    declared = declared_privileges(TEST_ENVIRONMENT)

    assert declared[SIMULATION_SERVICE_ROLE]["cliff_impacts"] == READ_INSERT | {
        update_columns(*SERVICE_RUN_STATE_COLUMNS)
    }
    assert declared[MODAL_WORKER_ROLE]["cliff_impacts"] == READ | {
        update_columns(*WORKER_RUN_STATE_COLUMNS, "cliff_gap", "cliff_share")
    }
    assert declared[RUNTIME_ROLE]["cliff_impacts"] == READ
    for role in (CATALOG_WRITER_ROLE, stage12_role(TEST_ENVIRONMENT)):
        assert declared[role]["cliff_impacts"] == NO_ACCESS, role


def test_api_v1_creates_and_reads_dynamics_but_never_changes_them() -> None:
    """``POST /v2/dynamics`` and the v1-to-v2 copy create dynamics, as policies.

    A dynamic is immutable once stored, so API v1 reads and inserts
    them and never updates or deletes one. The simulation service and its
    Modal workers read them for a run; no other role has access.
    """
    declared = declared_privileges(TEST_ENVIRONMENT)

    assert declared[RUNTIME_ROLE]["dynamics"] == READ_INSERT
    assert declared[RUNTIME_ROLE]["dynamics"] == declared[RUNTIME_ROLE]["policies"]
    assert declared[SIMULATION_SERVICE_ROLE]["dynamics"] == READ
    assert declared[MODAL_WORKER_ROLE]["dynamics"] == READ
    assert declared[CATALOG_WRITER_ROLE]["dynamics"] == NO_ACCESS


def test_dynamic_parameters_are_granted_as_policy_parameters_are() -> None:
    """The two dynamic parameter tables take the policy parameter tables' grants.

    Catalog publication inserts and analyzes both, and catalog pruning deletes
    current-law values from the values table; nothing updates either. API v1
    reads both and inserts a
    dynamic's values, which a run of the simulation service and its Modal
    workers reads. Comparison runs never read them.
    """
    declared = declared_privileges(TEST_ENVIRONMENT)

    for policy_table, dynamic_table in (
        ("parameters", "dynamic_parameters"),
        ("parameter_values", "dynamic_parameter_values"),
    ):
        for role in (
            RUNTIME_ROLE,
            SIMULATION_SERVICE_ROLE,
            MODAL_WORKER_ROLE,
            stage12_role(TEST_ENVIRONMENT),
        ):
            assert declared[role][dynamic_table] == declared[role][policy_table], (
                role,
                dynamic_table,
            )
    assert declared[RUNTIME_ROLE]["dynamic_parameter_values"] == READ_INSERT
    # Publication only inserts both tables' rows, and pruning deletes only
    # current-law values: nothing updates either.
    assert declared[CATALOG_WRITER_ROLE]["dynamic_parameters"] == READ_INSERT | {
        TablePrivilege.MAINTAIN
    }


def test_api_v1_saves_users_dynamics_as_it_saves_their_policies() -> None:
    """Users' saved dynamics are written as saved policies are, by API v1 alone.

    API v1 creates, renames, repoints and deletes a user's saved dynamics, and
    moves a browser's saved dynamics to the account it signs in to, so it holds
    every privilege it holds on ``user_policies``. The simulation service, its
    Modal workers and the catalog writer never read them.
    """
    declared = declared_privileges(TEST_ENVIRONMENT)

    assert declared[RUNTIME_ROLE]["user_dynamics"] == READ_WRITE
    assert (
        declared[RUNTIME_ROLE]["user_dynamics"]
        == declared[RUNTIME_ROLE]["user_policies"]
    )
    for role, tables in declared.items():
        if role != RUNTIME_ROLE:
            assert tables["user_dynamics"] == NO_ACCESS, role
