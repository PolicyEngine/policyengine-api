"""The v2 privilege manifest covers every table and every connector's needs.

Rule ``api.v2.runtime-privileges-declared`` (rules/registry.toml).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa

from policyengine_api.data.v2 import models
from policyengine_api.data.v2.models import V2_METADATA
from policyengine_api.data.v2.privilege_requirements import (
    required_privileges,
    undeclared_requirements,
)
from policyengine_api.data.v2.privileges import (
    CATALOG_WRITER_ROLE,
    NO_ACCESS,
    READ_WRITE,
    RUNTIME_ROLE,
    TABLE_ACCESS,
    TEMPORARY_VIEW_TABLES,
    InvalidDeploymentEnvironmentError,
    TablePrivilege,
    declared_privileges,
    stage12_role,
)

PROJECT_ROOT = Path(__file__).parents[3]
SERVICES_ROOT = PROJECT_ROOT / "policyengine_api" / "services" / "v2"
PROOF_FIXTURES = PROJECT_ROOT / "rules/fixtures/api.v2.runtime-privileges-declared"
STAGE12_PACKAGES = frozenset({"comparison_runs"})
TEST_ENVIRONMENT = "staging"


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
        f"{missing.connector}: {missing.privilege} on {missing.table} "
        f"({missing.reason})"
        for missing in undeclared_requirements(requirements, declared)
    ]


def test_every_v2_table_has_an_entry_for_every_managed_role() -> None:
    metadata_tables = {table.name for table in V2_METADATA.tables.values()}

    assert set(TABLE_ACCESS) == metadata_tables | {"alembic_version"}
    for role, privileges_by_table in declared_privileges(TEST_ENVIRONMENT).items():
        assert set(privileges_by_table) == set(TABLE_ACCESS) | set(
            TEMPORARY_VIEW_TABLES
        ), role


def test_each_temporary_view_grants_every_role_what_its_table_grants() -> None:
    """A view under a renamed table's earlier name serves the earlier release.

    That release reads and writes the table through the view, so each role
    needs on the view exactly what it holds on the table.
    """
    metadata_tables = {table.name for table in V2_METADATA.tables.values()}

    assert TEMPORARY_VIEW_TABLES == {"user_policies": "user_policy_associations"}
    for view, table in TEMPORARY_VIEW_TABLES.items():
        assert view not in metadata_tables
        assert table in metadata_tables
        for role, privileges_by_table in declared_privileges(TEST_ENVIRONMENT).items():
            assert privileges_by_table[view] == privileges_by_table[table], role
    assert declared_privileges(TEST_ENVIRONMENT)[RUNTIME_ROLE]["user_policies"] == (
        READ_WRITE
    )


def test_v2_schema_has_no_sequences_the_manifest_would_need_to_cover() -> None:
    sequence_columns = [
        f"{table.name}.{column.name}"
        for table in V2_METADATA.tables.values()
        for column in table.columns
        if isinstance(column.default, sa.Sequence)
        or column.identity is not None
        or (
            column.primary_key
            and len(table.primary_key.columns) == 1
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


def test_declared_privileges_name_the_three_managed_roles() -> None:
    assert set(declared_privileges("production")) == {
        RUNTIME_ROLE,
        CATALOG_WRITER_ROLE,
        "policyengine_stage12_production",
    }


def test_rule_proof_runtime_privileges_declared() -> None:
    """Proof for rule api.v2.runtime-privileges-declared (rules/registry.toml).

    The bad fixture repeats the mistake behind issue #3977: a runtime connector
    reads ``legacy_policy_mappings``, which the runtime role had no grant on.
    """
    runtime_before_3977 = dict.fromkeys(TABLE_ACCESS, NO_ACCESS) | {
        "user_policy_associations": READ_WRITE
    }
    table_by_model = _table_by_model()

    bad = required_privileges(PROOF_FIXTURES / "reads_bad.py", table_by_model)
    good = required_privileges(PROOF_FIXTURES / "reads_good.py", table_by_model)

    assert [
        (missing.table, missing.privilege)
        for missing in undeclared_requirements(bad, runtime_before_3977)
    ] == [("legacy_policy_mappings", TablePrivilege.SELECT)]
    assert undeclared_requirements(good, runtime_before_3977) == []
