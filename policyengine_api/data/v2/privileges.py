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
temporary view under a renamed table's earlier name (``TEMPORARY_VIEW_TABLES``)
is declared with its table's privileges.

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

The migration role (``policyengine_v2_migrator``) owns every table, and
Supabase's ``postgres`` role administers the project; neither is managed here.

Extra privileges a database holds beyond this manifest are reported, never
revoked. The v2 schema has no sequences (every key is a UUID); a test fails if
one appears, so the manifest can be extended to cover it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

RUNTIME_ROLE: Final = "policyengine_v2_runtime"
CATALOG_WRITER_ROLE: Final = "policyengine_v2_catalog_writer"
STAGE12_ROLE_PREFIX: Final = "policyengine_stage12_"
PERSISTENT_ENVIRONMENTS: Final = frozenset({"staging", "production"})
ENVIRONMENT_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


class TablePrivilege(StrEnum):
    """A PostgreSQL table privilege the manifest can declare."""

    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


NO_ACCESS: Final[frozenset[TablePrivilege]] = frozenset()
READ: Final = frozenset({TablePrivilege.SELECT})
READ_INSERT: Final = frozenset({TablePrivilege.SELECT, TablePrivilege.INSERT})
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

    runtime: frozenset[TablePrivilege]
    catalog_writer: frozenset[TablePrivilege]
    stage12: frozenset[TablePrivilege]


def _access(
    *,
    runtime: frozenset[TablePrivilege] = NO_ACCESS,
    catalog_writer: frozenset[TablePrivilege] = NO_ACCESS,
    stage12: frozenset[TablePrivilege] = NO_ACCESS,
) -> TableAccess:
    return TableAccess(runtime=runtime, catalog_writer=catalog_writer, stage12=stage12)


TABLE_ACCESS: Final[dict[str, TableAccess]] = {
    # Alembic's revision record; the catalog writer checks the schema revision.
    "alembic_version": _access(catalog_writer=READ),
    # Simulation-domain result tables, unused by the managed roles.
    "aggregates": _access(),
    "budget_summary": _access(),
    "change_aggregates": _access(),
    "congressional_district_impacts": _access(),
    "constituency_impacts": _access(),
    "decile_impacts": _access(),
    "dynamics": _access(),
    "household_jobs": _access(),
    "inequality": _access(),
    "intra_decile_impacts": _access(),
    "local_authority_impacts": _access(),
    "poverty": _access(),
    "program_statistics": _access(),
    "report_runs": _access(catalog_writer=READ),
    "reports": _access(catalog_writer=READ),
    "simulations": _access(catalog_writer=READ),
    # Metadata catalog: the catalog writer publishes it, the Public API reads it.
    "dataset_versions": _access(catalog_writer=READ),
    "datasets": _access(runtime=READ, catalog_writer=READ_INSERT_UPDATE),
    "parameter_nodes": _access(runtime=READ, catalog_writer=READ_INSERT_UPDATE),
    # Written with each catalog version, and for versions stored before it.
    "parameter_tree_children": _access(runtime=READ, catalog_writer=READ_INSERT),
    # The Public API also inserts a v2 policy's own parameter values.
    "parameter_values": _access(runtime=READ_INSERT, catalog_writer=READ_INSERT_UPDATE),
    "parameters": _access(runtime=READ, catalog_writer=READ_INSERT_UPDATE),
    "regions": _access(runtime=READ, catalog_writer=READ_INSERT_UPDATE),
    "tax_benefit_model_versions": _access(
        runtime=READ, catalog_writer=READ_INSERT_UPDATE
    ),
    "tax_benefit_models": _access(runtime=READ, catalog_writer=READ_INSERT_UPDATE),
    "variables": _access(runtime=READ, catalog_writer=READ_INSERT_UPDATE),
    # v2 policies and households, created by the native routes and by Stage 10
    # dual-write. A copy locks its mapping row (FOR UPDATE), which needs UPDATE.
    "households": _access(runtime=READ_INSERT),
    "legacy_household_mappings": _access(runtime=READ_INSERT_UPDATE),
    "legacy_policy_mappings": _access(runtime=READ_INSERT_UPDATE),
    "policies": _access(runtime=READ_INSERT),
    # Stage 10 saved-policy mirror.
    "legacy_user_mappings": _access(runtime=READ_WRITE),
    "legacy_user_policy_mappings": _access(runtime=READ_WRITE),
    # Users and their saved work (Stage 12A).
    "user_household_associations": _access(runtime=READ_WRITE),
    "user_identities": _access(runtime=READ_WRITE),
    "user_policy_associations": _access(runtime=READ_WRITE),
    "user_report_associations": _access(runtime=READ_WRITE),
    "user_simulation_associations": _access(runtime=READ_WRITE),
    "users": _access(runtime=READ_WRITE),
    # Temporary Stage 12 comparison-run tables.
    "stage12_evaluation_reports": _access(runtime=READ_WRITE, stage12=READ_WRITE),
    "stage12_evaluation_simulations": _access(runtime=READ_WRITE, stage12=READ_WRITE),
}


# Temporary views under a renamed table's earlier name, each mapped to the
# table it shows. The Public API release that still serves during a deploy, or
# after a rollback to it, reads and writes the table through the view, so every
# role holds on the view what it holds on the table. A later revision drops
# each view, and its entry here goes with it.
TEMPORARY_VIEW_TABLES: Final[dict[str, str]] = {
    # Revision fa7fa1035444 renamed user_policies to user_policy_associations.
    "user_policies": "user_policy_associations",
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
) -> dict[str, dict[str, frozenset[TablePrivilege]]]:
    """Return each managed role's declared privileges, keyed by role then table.

    Each temporary view is declared with its table's privileges.
    """
    stage12 = stage12_role(deployment_environment)
    access_by_relation = TABLE_ACCESS | {
        view: TABLE_ACCESS[table] for view, table in TEMPORARY_VIEW_TABLES.items()
    }
    return {
        RUNTIME_ROLE: {
            relation: access.runtime for relation, access in access_by_relation.items()
        },
        CATALOG_WRITER_ROLE: {
            relation: access.catalog_writer
            for relation, access in access_by_relation.items()
        },
        stage12: {
            relation: access.stage12 for relation, access in access_by_relation.items()
        },
    }
