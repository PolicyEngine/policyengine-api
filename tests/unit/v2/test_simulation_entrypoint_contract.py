"""The simulation service contract is shared without the economy report package.

Saved reports and simulations check v2 references with the simulation
service, and the adapter implements the service's routes; neither depends on
how economy reports are served.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from policyengine_api.constants import REPO

ECONOMY_REPORT_PACKAGE = "policyengine_api.services.v2.economy_reports"
INDEPENDENT_MODULES = (
    "policyengine_api/libs/simulation_economy_reports.py",
    "policyengine_api/fastapi_routes/v2/user_resources.py",
    "policyengine_api/services/v2/associations/types.py",
    "policyengine_api/services/v2/associations/validators.py",
    "policyengine_api/services/v2/simulation_refs/services.py",
    "policyengine_api/services/v2/simulation_refs/validators.py",
    "policyengine_api/services/v2/user_reports/services.py",
    "policyengine_api/services/v2/user_simulations/services.py",
)


def _imported_modules(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return imported


@pytest.mark.parametrize("module_path", INDEPENDENT_MODULES)
def test_module_uses_the_shared_simulation_contract(module_path: str) -> None:
    imported = _imported_modules(Path(REPO) / module_path)

    assert not {
        module
        for module in imported
        if module == ECONOMY_REPORT_PACKAGE
        or module.startswith(f"{ECONOMY_REPORT_PACKAGE}.")
    }
