"""Database-access boundaries for run and specification services."""

from pathlib import Path

import pytest


SERVICE_ROOT = Path(__file__).parents[3] / "policyengine_api" / "services"


@pytest.mark.parametrize(
    "module_name",
    [
        "simulation_run_service.py",
        "simulation_spec_service.py",
        "report_run_service.py",
        "report_spec_service.py",
    ],
)
def test_run_and_spec_services_do_not_issue_queries_directly(module_name):
    source = (SERVICE_ROOT / module_name).read_text(encoding="utf-8")
    assert ".query(" not in source
    assert "from policyengine_api.data import database" not in source
