"""The simulation-domain tables and models stay out of the Public API.

The simulation service owns household jobs, simulations, reports, report runs
and their outputs in its own ``simulation`` schema. A v2 revision dropped the
Public API's dormant copies of those tables and removed their models, so no
code here may import those models again and no v2 model may declare those
tables again.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from policyengine_api.constants import REPO
from policyengine_api.data.v2.metadata_validation import SIMULATION_SERVICE_TABLES
from policyengine_api.data.v2.models import V2_METADATA

if TYPE_CHECKING:
    from pathlib import Path

V2_MODELS_PACKAGE = "policyengine_api.data.v2.models"
REMOVED_MODEL_NAMES = frozenset(
    {
        "AggregateOutput",
        "AggregateType",
        "BudgetSummary",
        "ChangeAggregate",
        "CongressionalDistrictImpact",
        "ConstituencyImpact",
        "DecileImpact",
        "DecileType",
        "GeographicImpactBase",
        "HouseholdJob",
        "HouseholdJobStatus",
        "Inequality",
        "IntraDecileImpact",
        "LocalAuthorityImpact",
        "OutputStatus",
        "Poverty",
        "ProgramStatistics",
        "Report",
        "ReportRun",
        "ReportRunStatus",
        "ReportRunTrigger",
        "Simulation",
        "SimulationStatus",
        "SimulationType",
    }
)
REMOVED_MODULES = frozenset(
    {
        f"{V2_MODELS_PACKAGE}.reports",
        f"{V2_MODELS_PACKAGE}.simulations",
        "policyengine_api.data.v2.report_runs",
    }
)
SCANNED_DIRECTORIES = ("policyengine_api", "scripts", "tests")
SCANNED_FILES = ("migrations/v2/env.py",)
FIXTURES = REPO / "rules/fixtures/api.v2.simulation-tables-stay-removed"


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(REPO).with_suffix("").parts)


def _imported_module(node: ast.ImportFrom, importing_module: str) -> str:
    if node.level == 0:
        return node.module or ""
    package_parts = importing_module.split(".")[: -node.level]
    return ".".join([*package_parts, *([node.module] if node.module else [])])


def removed_model_imports(path: Path, *, module_name: str | None = None) -> list[str]:
    """Return each removed simulation-domain module or model that ``path`` imports."""
    importing_module = module_name or _module_name(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                alias.name for alias in node.names if alias.name in REMOVED_MODULES
            )
        elif isinstance(node, ast.ImportFrom):
            imported_module = _imported_module(node, importing_module)
            if imported_module in REMOVED_MODULES:
                found.append(imported_module)
            elif imported_module == V2_MODELS_PACKAGE or imported_module.startswith(
                f"{V2_MODELS_PACKAGE}."
            ):
                found.extend(
                    f"{imported_module}.{alias.name}"
                    for alias in node.names
                    if alias.name in REMOVED_MODEL_NAMES
                    or f"{imported_module}.{alias.name}" in REMOVED_MODULES
                )
    return found


def _scanned_files() -> list[Path]:
    files = [REPO / relative_path for relative_path in SCANNED_FILES]
    for directory in SCANNED_DIRECTORIES:
        files.extend(sorted((REPO / directory).rglob("*.py")))
    return files


def test_no_module_imports_a_removed_simulation_model() -> None:
    offending_imports = {
        str(path.relative_to(REPO)): imports
        for path in _scanned_files()
        if (imports := removed_model_imports(path))
    }

    assert not offending_imports, (
        "The simulation service owns these models; read its API instead: "
        f"{offending_imports}"
    )


def test_v2_metadata_declares_no_simulation_service_table() -> None:
    assert SIMULATION_SERVICE_TABLES.isdisjoint(V2_METADATA.tables)
    assert not any(
        (REPO / "policyengine_api/data/v2" / relative_path).exists()
        for relative_path in ("models/reports.py", "models/simulations.py")
    )


def test_rule_proof_simulation_tables_stay_removed() -> None:
    """Proof for rule api.v2.simulation-tables-stay-removed (rules/registry.toml)."""
    fixture_module = "policyengine_api.data.v2.example"
    assert removed_model_imports(
        FIXTURES / "bad_import.py", module_name=fixture_module
    ) == [
        "policyengine_api.data.v2.report_runs",
        "policyengine_api.data.v2.models.HouseholdJob",
        "policyengine_api.data.v2.models.Report",
        "policyengine_api.data.v2.models.reports",
        "policyengine_api.data.v2.models.simulations",
    ]
    assert (
        removed_model_imports(FIXTURES / "good_import.py", module_name=fixture_module)
        == []
    )
