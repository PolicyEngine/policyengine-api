from pathlib import Path

import pytest


SERVICE_ROOT = Path(__file__).parents[3] / "policyengine_api" / "services"


@pytest.mark.parametrize(
    "module_name", ["simulation_service.py", "report_output_service.py"]
)
def test_orchestration_services_do_not_access_database_connections(module_name):
    source = (SERVICE_ROOT / module_name).read_text(encoding="utf-8")
    assert "from policyengine_api.data import database" not in source
    assert "database.transaction(" not in source
