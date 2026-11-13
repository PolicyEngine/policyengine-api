"""The table privileges each managed v2 database role holds.

This manifest is the source of truth for what the application roles may do
in the v2 Supabase database. ``scripts/reconcile_v2_privileges.py`` grants
whatever it declares after every schema upgrade and checks the result before
a deploy (rule ``api.v2.deployed-privileges-match``). A unit test compares it
with the privileges the connector code needs (rule
``api.v2.runtime-privileges-declared``), and the cross-database integration
tests run the services as these roles (rule
``api.v2.runtime-privileges-tested-as-runtime-role``).

Every table in the v2 SQLModel metadata, plus ``alembic_version``, has an entry
for every managed role, so "no access" is a decision, not an omission. A
privilege is on the whole table, or a ``ColumnPrivilege`` on the columns it
names; a role never holds both kinds of the same privilege on one table, since
the whole-table one would let it change every column.

Roles and what decides their privileges:

- ``policyengine_v2_runtime``: the Public API on Cloud Run. Every connector
  module under ``policyengine_api/services/v2/`` except ``comparison_runs``
  runs as this role.
- ``policyengine_stage12_<environment>``: the simulation API and its Modal
  worker. The ``comparison_runs`` connectors describe their operations on the
  temporary Stage 12 tables (``docs/migration/stage-12-worker-contract.md``).
- ``policyengine_v2_catalog_writer``: the metadata catalog publication
  (``scripts/publish_v2_metadata_catalog.py``). Its privileges follow what
  publication writes and reads; its code isn't organized as connector modules,
  so the deploy check, not the connector analysis, covers it.
- ``policyengine_v2_simulation_service``: the simulation API on Cloud Run. It
  creates simulations, reports, their runs, budget-window runs and household
  jobs, and reads the policy, dynamic, household and catalog rows a run needs.
  It starts the Modal calls of runs and household jobs, so it may update their
  status, Modal call ID, error and completion columns: it records a call's ID
  once Modal accepts the call, and fails the run when Modal refuses it. It
  starts a budget-window run's first years at submit, so it may update the
  window run's status, error and completion columns, to fail it at once when
  Modal refuses those years' calls.
- ``policyengine_v2_modal_worker``: the simulation API's Modal workers. They
  write the status of the runs and household jobs they were given, and their
  results, and read the rows a run needs. They also write a budget-window
  run's status, error and times: each year's coordinator starts the window's
  next unstarted year when its own year finishes, the last year to finish
  marks the window succeeded, and a failed year fails it.

Both simulation API roles update only the columns ``update_columns`` names, so
the database refuses any change to what a run is (its simulation or report,
versions, dataset, region, year, simulation runs or budget-window run) or to
what a budget-window run is (its report, catalog version, trigger or whether
it calculates again). It doesn't limit a worker to its own run; the workers'
code does. Their code lives in the simulation API's repository, so the deploy
check covers them here.

The Public API reads the simulation tables it serves, and writes none of them.

The migration role (``policyengine_v2_migrator``) owns every table, and
Supabase's ``postgres`` role administers the project; neither is managed here.

Extra privileges a database holds beyond this manifest are reported, never
revoked. The v2 schema has no sequences (every key is a UUID); a test fails if
one appears, so the manifest can be extended to cover it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

RUNTIME_ROLE: Final = "policyengine_v2_runtime"
CATALOG_WRITER_ROLE: Final = "policyengine_v2_catalog_writer"
SIMULATION_SERVICE_ROLE: Final = "policyengine_v2_simulation_service"
MODAL_WORKER_ROLE: Final = "policyengine_v2_modal_worker"
STAGE12_ROLE_PREFIX: Final = "policyengine_stage12_"
PERSISTENT_ENVIRONMENTS: Final = frozenset({"staging", "production"})
# Declared roles an operator hasn't created in staging and production yet. While
# one is missing, the deploy's ``apply`` and ``verify`` skip it and name it,
# instead of failing; once it exists they grant and check its privileges.
# Remove a role from this set when it exists in both environments, so that its
# absence fails the deploy again.
ROLES_AWAITING_PROVISIONING: Final[frozenset[str]] = frozenset()
ENVIRONMENT_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


class TablePrivilege(StrEnum):
    """A PostgreSQL table privilege the manifest can declare."""

    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


@dataclass(frozen=True)
class ColumnPrivilege:
    """A privilege on some of a table's columns instead of the whole table.

    PostgreSQL refuses a statement that uses the privilege on any other column.
    """

    privilege: TablePrivilege
    columns: frozenset[str]


DeclaredPrivilege = TablePrivilege | ColumnPrivilege


def update_columns(*columns: str) -> ColumnPrivilege:
    """Declare ``UPDATE`` on only the named columns."""
    return ColumnPrivilege(TablePrivilege.UPDATE, frozenset(columns))


NO_ACCESS: Final[frozenset[TablePrivilege]] = frozenset()
READ: Final = frozenset({TablePrivilege.SELECT})
READ_INSERT: Final = frozenset({TablePrivilege.SELECT, TablePrivilege.INSERT})
READ_INSERT_DELETE: Final = frozenset(
    {TablePrivilege.SELECT, TablePrivilege.INSERT, TablePrivilege.DELETE}
)
READ_INSERT_UPDATE: Final = frozenset(
    {TablePrivilege.SELECT, TablePrivilege.INSERT, TablePrivilege.UPDATE}
)
READ_WRITE: Final = frozenset(
    {
        TablePrivilege.SELECT,
        TablePrivilege.INSERT,
        TablePrivilege.UPDATE,
        TablePrivilege.DELETE,
    }
)


@dataclass(frozen=True)
class TableAccess:
    """What each managed role may do on one table."""

    runtime: frozenset[DeclaredPrivilege]
    catalog_writer: frozenset[DeclaredPrivilege]
    stage12: frozenset[DeclaredPrivilege]
    simulation_service: frozenset[DeclaredPrivilege]
    modal_worker: frozenset[DeclaredPrivilege]


def _access(
    *,
    runtime: frozenset[DeclaredPrivilege] = NO_ACCESS,
    catalog_writer: frozenset[DeclaredPrivilege] = NO_ACCESS,
    stage12: frozenset[DeclaredPrivilege] = NO_ACCESS,
    simulation_service: frozenset[DeclaredPrivilege] = NO_ACCESS,
    modal_worker: frozenset[DeclaredPrivilege] = NO_ACCESS,
) -> TableAccess:
    return TableAccess(
        runtime=runtime,
        catalog_writer=catalog_writer,
        stage12=stage12,
        simulation_service=simulation_service,
        modal_worker=modal_worker,
    )


# The simulation API creates these rows and its Modal workers read them.
_SIMULATION_DEFINITION = _access(
    runtime=READ, simulation_service=READ_INSERT, modal_worker=READ
)
# A run's state, which the Modal worker running it writes.
_RUN_STATE_COLUMNS: Final = (
    "status",
    "modal_call_id",
    "error_message",
    "started_at",
    "completed_at",
    "updated_at",
)
# The state the simulation service writes for a run whose Modal call it starts:
# the call's ID once Modal accepts the call, or the failure when Modal refuses
# it.
_CALL_START_COLUMNS: Final = (
    "status",
    "modal_call_id",
    "error_message",
    "completed_at",
    "updated_at",
)


# A budget-window run's state, which the Modal workers write. A window run has
# no Modal call of its own: the workers record when it started, each year's
# coordinator starts the window's next unstarted year when its own year
# finishes, the last year to finish marks the window succeeded, and a failed
# year fails it.
_WINDOW_RUN_STATE_COLUMNS: Final = (
    "status",
    "error_message",
    "started_at",
    "completed_at",
    "updated_at",
)
# The state the simulation service writes for a budget-window run whose first
# years' Modal calls it starts at submit: the failure when Modal refuses them.
_WINDOW_FAILURE_COLUMNS: Final = (
    "status",
    "error_message",
    "completed_at",
    "updated_at",
)


def _run_table(
    *result_columns: str, catalog_writer: frozenset[DeclaredPrivilege] = NO_ACCESS
) -> TableAccess:
    """Access to a run table whose Modal worker writes the named result columns."""
    return _access(
        runtime=READ,
        catalog_writer=catalog_writer,
        simulation_service=READ_INSERT | {update_columns(*_CALL_START_COLUMNS)},
        modal_worker=READ | {update_columns(*_RUN_STATE_COLUMNS, *result_columns)},
    )


# The Modal workers write results, keyed by run, once each.
_RESULT = _access(runtime=READ, modal_worker=READ_INSERT)
# What a run needs from the Public API's policies, dynamics, households and
# catalog.
_RUN_INPUT_READS: Final = {"simulation_service": READ, "modal_worker": READ}


TABLE_ACCESS: Final[dict[str, TableAccess]] = {
    # Alembic's revision record; the catalog writer checks the schema revision.
    "alembic_version": _access(catalog_writer=READ),
    # Custom totals, unused until they return.
    "aggregates": _access(),
    "change_aggregates": _access(),
    # A simulation's or household job's dynamic, which a run reads.
    "dynamics": _access(**_RUN_INPUT_READS),
    # Simulations, reports, their runs and household jobs. The catalog writer
    # checks that publication leaves the rows of three of them untouched.
    "budget_window_runs": _access(
        runtime=READ,
        simulation_service=READ_INSERT | {update_columns(*_WINDOW_FAILURE_COLUMNS)},
        modal_worker=READ | {update_columns(*_WINDOW_RUN_STATE_COLUMNS)},
    ),
    "household_jobs": _run_table("result"),
    "report_runs": _run_table(
        "baseline_cliff_gap",
        "baseline_cliff_share",
        "reform_cliff_gap",
        "reform_cliff_share",
        "spm_provenance",
        "data_version",
        catalog_writer=READ,
    ),
    "reports": replace(_SIMULATION_DEFINITION, catalog_writer=READ),
    "simulation_runs": _run_table("output_uri", "output_sha256", "household_result"),
    "simulations": replace(_SIMULATION_DEFINITION, catalog_writer=READ),
    # Results of simulation runs and report runs.
    "labor_supply_decile_responses": _RESULT,
    "labor_supply_responses": _RESULT,
    "budget_summary": _RESULT,
    "congressional_district_impacts": _RESULT,
    "constituency_impacts": _RESULT,
    "decile_impacts": _RESULT,
    "inequality": _RESULT,
    "intra_decile_impacts": _RESULT,
    "local_authority_impacts": _RESULT,
    "poverty": _RESULT,
    "program_statistics": _RESULT,
    # The UK areas disclosure control withheld from a local-area run's results.
    "withheld_area_codes": _RESULT,
    # Metadata catalog: the catalog writer publishes it, the Public API reads it.
    "dataset_versions": _access(catalog_writer=READ),
    "datasets": _access(
        runtime=READ, catalog_writer=READ_INSERT_UPDATE, **_RUN_INPUT_READS
    ),
    "parameter_nodes": _access(runtime=READ, catalog_writer=READ_INSERT_UPDATE),
    # Written by catalog publication for each version it publishes, from the
    # installed packages' catalog; never rewritten. Catalog pruning deletes an
    # older version's file, which publishing that version again writes back.
    "parameter_search_files": _access(runtime=READ, catalog_writer=READ_INSERT_DELETE),
    # Written with each catalog version that publication publishes; catalog
    # pruning deletes an older version's rows.
    "parameter_tree_children": _access(runtime=READ, catalog_writer=READ_INSERT_DELETE),
    # The Public API also inserts a v2 policy's own parameter values. Catalog
    # pruning deletes an older version's current-law values (those with no
    # policy or dynamic), never a policy's or a dynamic's.
    "parameter_values": _access(
        runtime=READ_INSERT, catalog_writer=READ_WRITE, **_RUN_INPUT_READS
    ),
    "parameters": _access(
        runtime=READ, catalog_writer=READ_INSERT_UPDATE, **_RUN_INPUT_READS
    ),
    "regions": _access(
        runtime=READ, catalog_writer=READ_INSERT_UPDATE, **_RUN_INPUT_READS
    ),
    # Catalog publication updates a version's time periods,
    # catalog_last_published_at and spm_availability, and catalog pruning its
    # catalog_values_pruned_at.
    "tax_benefit_model_versions": _access(
        runtime=READ, catalog_writer=READ_INSERT_UPDATE, **_RUN_INPUT_READS
    ),
    "tax_benefit_models": _access(
        runtime=READ, catalog_writer=READ_INSERT_UPDATE, **_RUN_INPUT_READS
    ),
    "variables": _access(runtime=READ, catalog_writer=READ_INSERT_UPDATE),
    # v2 policies and households, created by the native routes and by Stage 10
    # dual-write. A copy locks its mapping row (FOR UPDATE), which needs UPDATE.
    "households": _access(runtime=READ_INSERT, **_RUN_INPUT_READS),
    "legacy_household_mappings": _access(runtime=READ_INSERT_UPDATE),
    "legacy_policy_mappings": _access(runtime=READ_INSERT_UPDATE),
    "policies": _access(runtime=READ_INSERT, **_RUN_INPUT_READS),
    # Stage 10 saved-policy mirror.
    "legacy_user_mappings": _access(runtime=READ_WRITE),
    "legacy_user_policy_mappings": _access(runtime=READ_WRITE),
    # Served countries; the migration that creates the table inserts its rows,
    # and the Public API reads them.
    "countries": _access(runtime=READ),
    # Users and their saved work (Stage 12A).
    "user_household_associations": _access(runtime=READ_WRITE),
    "user_identities": _access(runtime=READ_WRITE),
    "user_policies": _access(runtime=READ_WRITE),
    "user_report_associations": _access(runtime=READ_WRITE),
    "user_simulation_associations": _access(runtime=READ_WRITE),
    "users": _access(runtime=READ_WRITE),
    # Each change of a signed-in user's type, recorded by the admin routes and
    # the type script and never changed afterwards.
    "user_type_changes": _access(runtime=READ_INSERT),
    # Temporary Stage 12 comparison-run tables.
    "stage12_evaluation_reports": _access(runtime=READ_WRITE, stage12=READ_WRITE),
    "stage12_evaluation_simulations": _access(runtime=READ_WRITE, stage12=READ_WRITE),
}


class InvalidDeploymentEnvironmentError(ValueError):
    """Raised for a deployment environment that can't name a Stage 12 role."""


def stage12_role(deployment_environment: str) -> str:
    """Return the Stage 12 role name for a deployment environment.

    Staging and production name their persistent roles; a disposable test
    database may use any short lowercase name.
    """
    if ENVIRONMENT_PATTERN.fullmatch(deployment_environment) is None:
        msg = (
            "the deployment environment must be lowercase letters, digits or "
            f"underscores, got {deployment_environment!r}"
        )
        raise InvalidDeploymentEnvironmentError(msg)
    return f"{STAGE12_ROLE_PREFIX}{deployment_environment}"


def declared_privileges(
    deployment_environment: str,
) -> dict[str, dict[str, frozenset[DeclaredPrivilege]]]:
    """Return each managed role's declared privileges, keyed by role then table."""
    stage12 = stage12_role(deployment_environment)
    return {
        RUNTIME_ROLE: {table: access.runtime for table, access in TABLE_ACCESS.items()},
        CATALOG_WRITER_ROLE: {
            table: access.catalog_writer for table, access in TABLE_ACCESS.items()
        },
        stage12: {table: access.stage12 for table, access in TABLE_ACCESS.items()},
        SIMULATION_SERVICE_ROLE: {
            table: access.simulation_service for table, access in TABLE_ACCESS.items()
        },
        MODAL_WORKER_ROLE: {
            table: access.modal_worker for table, access in TABLE_ACCESS.items()
        },
    }
